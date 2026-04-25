"""
Node implementations for the hazard risk reviewer.

Two nodes plus one Send dispatcher:

- dispatch_requirement_reviews: LangGraph Send fan-out — one Send per
  requirement traced from the HazardRecord. Each Send delivers
  {"hazard": HazardRecord, "requirement": Requirement} into requirement_reviewer.

- RequirementReviewerNode: invokes the entire compiled test_suite_reviewer
  graph as an atomic subgraph for one requirement. Maps the Send payload to
  RTMReviewState on entry; collapses the RTM final state into a
  RequirementReview model on exit. Results accumulate via operator.add on
  HazardReviewState.requirement_reviews.

- HazardSynthesizerNode: StandardLLMNode that applies the H1-H5 rubric over
  the hazard fields plus all per-requirement M1-M5 assessments and emits a
  HazardAssessment.
"""

from typing import Any, List, Optional

from langgraph.types import Send

from autoqa.components.clients import RateLimitOpenAIClient
from autoqa.components.shared.nodes import BaseLLMNode, StandardLLMNode
from autoqa.components.test_suite_reviewer.pipeline import RTMReviewerRunnable
from autoqa.core.config import settings
from autoqa.prj_logger import ProjectLogger
from autoqa.utils import render_prompt

from .core import (
    HazardAssessment,
    HazardReviewState,
    RequirementReview,
)

project_logger = ProjectLogger(name="logger.hazard.nodes", log_file=settings.log_file_path)
project_logger.config()
logger = project_logger.get_logger()


def dispatch_requirement_reviews(state: HazardReviewState) -> List[Send]:
    """
    LangGraph Send dispatcher: fans out one Send per traced requirement so
    each requirement is reviewed in parallel by RequirementReviewerNode.
    Returns an empty list when the hazard or its requirements are missing.
    """
    hazard = state.get("hazard")
    if not hazard or not hazard.requirements:
        logger.warning("dispatch_requirement_reviews: no hazard/requirements, skipping fan-out")
        return []
    return [
        Send("requirement_reviewer", {"hazard": hazard, "requirement": req})
        for req in hazard.requirements
    ]


class RequirementReviewerNode:
    """
    Invokes the entire compiled test_suite_reviewer graph as an atomic
    subgraph for one requirement. The wrapped RTMReviewerRunnable is shared
    across all parallel Send fan-outs — its compiled graph is built once and
    reused per requirement (each invocation is independent state via
    LangGraph's MemorySaver semantics).
    """

    def __init__(self, rtm_runnable: RTMReviewerRunnable):
        self.rtm = rtm_runnable

    async def __call__(self, state: Any) -> HazardReviewState:
        # `state` is the per-Send payload, NOT a full HazardReviewState.
        hazard = state.get("hazard")
        requirement = state.get("requirement")
        if hazard is None or requirement is None:
            logger.warning("RequirementReviewerNode: missing hazard or requirement, skipping")
            return {"requirement_reviews": []}

        rtm_input = {
            "requirement": requirement,
            "test_cases": hazard.test_cases,
        }
        try:
            rtm_result = await self.rtm.graph.ainvoke(rtm_input)
        except Exception as e:
            logger.warning(
                "RequirementReviewerNode: RTM subgraph invocation failed for %s — %s",
                requirement.req_id, e,
            )
            return {
                "requirement_reviews": [
                    RequirementReview(requirement=requirement)
                ]
            }

        review = RequirementReview(
            requirement=requirement,
            synthesized_assessment=rtm_result.get("synthesized_assessment"),
            decomposed_requirement=rtm_result.get("decomposed_requirement"),
            test_suite=rtm_result.get("test_suite"),
            coverage_analysis=rtm_result.get("coverage_analysis", []),
        )
        return {"requirement_reviews": [review]}


class HazardSynthesizerNode(StandardLLMNode):
    """
    Applies the H1-H5 SoP-gating rubric over the full HazardRecord plus all
    per-requirement RequirementReview evidence accumulated by the parallel
    RequirementReviewerNode runs. Mirrors SynthesizerNode in
    test_suite_reviewer/nodes.py.
    """

    def _validate_state(self, state: HazardReviewState) -> bool:
        hazard = state.get("hazard")
        reviews = state.get("requirement_reviews")
        return hazard is not None and reviews is not None and len(reviews) > 0

    def _build_payload(self, state: HazardReviewState) -> dict:
        hazard = state.get("hazard")
        reviews = state.get("requirement_reviews")
        assert hazard is not None
        assert reviews is not None
        return {
            "hazard": hazard.model_dump(),
            "requirement_reviews": [r.model_dump() for r in reviews],
        }

    def _format_response(self, parsed_result: Optional[HazardAssessment]) -> HazardReviewState:
        return {"hazard_assessment": parsed_result}

    def _get_skip_response(self) -> HazardReviewState:
        return {"hazard_assessment": None}


# Factory functions

def make_requirement_reviewer_node(rtm_runnable: RTMReviewerRunnable) -> RequirementReviewerNode:
    """
    Create a RequirementReviewerNode that wraps the supplied
    RTMReviewerRunnable. The compiled RTM graph is shared across all
    parallel Send fan-outs.
    """
    return RequirementReviewerNode(rtm_runnable)


def make_hazard_synthesizer_node(
    client: RateLimitOpenAIClient,
    model: str,
    model_kwargs: dict,
    prompt_template: str = "hazard_synthesizer-v1.jinja2",
    **template_vars,
) -> HazardSynthesizerNode:
    """
    Create a HazardSynthesizerNode with prompt loaded from a Jinja2 template.

    Args:
        client: RateLimitOpenAIClient instance
        model: Model identifier string
        model_kwargs: Additional kwargs forwarded to chat_completion
        prompt_template: Filename of the Jinja2 template to render as the system prompt
        **template_vars: Optional variables to pass to the Jinja2 template

    Returns:
        HazardSynthesizerNode: configured synthesizer for the H1-H5 rubric
    """
    system_prompt = render_prompt(prompt_template, **template_vars)
    return HazardSynthesizerNode(
        client=client,
        model=model,
        response_model=HazardAssessment,
        system_prompt=system_prompt,
        model_kwargs=model_kwargs,
    )
