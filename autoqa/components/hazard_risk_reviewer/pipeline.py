"""
LangGraph pipeline for the hazard risk reviewer.

Graph structure (single hazard per invocation):

    START
      ↓ (conditional edge: dispatch_requirement_reviews → Send × N)
    REQUIREMENT_REVIEWER  × N parallel
      (each Send invokes the entire test_suite_reviewer subgraph atomically;
       results accumulate into requirement_reviews via operator.add)
      ↓
    HAZARD_SYNTHESIZER  (StandardLLMNode applying H1-H5 mandatory rubric)
      ↓
    END

Two nodes plus one Send dispatcher — simpler than RTMReviewerRunnable's
five-node graph because the hazard does not need its own decomposer; the
RTM subgraph already decomposes its requirement into specs and produces
M1-M5 findings the synthesizer can roll up into H1-H5.
"""

from pathlib import Path
from typing import Optional, Union

from langchain_core.runnables import Runnable
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from autoqa.components.clients import RateLimitOpenAIClient
from autoqa.components.test_suite_reviewer.pipeline import RTMReviewerRunnable
from autoqa.core.config import PromptConfig, settings
from autoqa.utils import save_graph_png

from .core import HazardReviewState
from .nodes import (
    dispatch_requirement_reviews,
    make_hazard_synthesizer_node,
    make_requirement_reviewer_node,
)


class HazardReviewerRunnable:
    """
    LangGraph-based hazard reviewer. Evaluates whether a HazardRecord's
    traced requirements + test cases provide reasonable assurance of safety
    against the hazard, applying the H1-H5 rubric defined by the
    review-hazard-mitigation-coverage skill.

    Each cited requirement on the hazard is fanned out to a parallel
    RequirementReviewerNode via the LangGraph Send API. Each
    RequirementReviewerNode invokes the full RTMReviewerRunnable subgraph
    atomically for that requirement, producing an M1-M5 SynthesizedAssessment
    plus the RTM byproducts (decomposed specs, summarized TCs, per-spec
    coverage_analysis). All RequirementReviews accumulate via operator.add.

    The HazardSynthesizerNode then applies the H1-H5 rubric over the full
    HazardRecord plus all per-requirement reviews and emits a single
    HazardAssessment with overall_verdict ∈ {Adequate, Partial, Inadequate}.
    """

    def __init__(
        self,
        client: RateLimitOpenAIClient,
        model: str,
        model_kwargs: dict = {},
        checkpointer: Union[MemorySaver, None] = None,
        prompt_config: Optional[PromptConfig] = None,
        rtm_runnable: Optional[RTMReviewerRunnable] = None,
    ):
        self.client = client
        self.model = model
        self.model_kwargs = model_kwargs
        self.checkpointer = checkpointer
        self.prompt_config = prompt_config if prompt_config is not None else settings.prompt_config
        # The RTM subgraph is built once and reused across all Send fan-outs.
        # Callers can inject a pre-built RTMReviewerRunnable to share a
        # single compiled graph between this service and an RTMReviewService.
        self.rtm = rtm_runnable or RTMReviewerRunnable(
            client=client,
            model=model,
            model_kwargs=model_kwargs,
            prompt_config=self.prompt_config,
        )
        self.graph = self.build()

    def build(self) -> Runnable:
        """
        Build the hazard review graph.

        Graph structure:
            START
              ↓ dispatch_requirement_reviews → Send × N
            ┌────────────────────────────────────┐
            │REQUIREMENT_REVIEWER × N (parallel) │
            │ (each invokes RTM subgraph atomically)
            └────────────────────────────────────┘
              ↓ (fan-in: operator.add on requirement_reviews)
            ┌────────────────────────────────────┐
            │HAZARD_SYNTHESIZER (H1-H5 rubric)   │
            └────────────────────────────────────┘
              ↓
            END
        """
        sg = StateGraph(HazardReviewState)

        requirement_reviewer = make_requirement_reviewer_node(self.rtm)
        hazard_synthesizer = make_hazard_synthesizer_node(
            self.client, self.model, self.model_kwargs,
            prompt_template=self.prompt_config.hazard_synthesizer,
        )

        sg.add_node("requirement_reviewer", requirement_reviewer)
        sg.add_node("hazard_synthesizer", hazard_synthesizer)

        # Fan-out via Send to N parallel requirement reviewers
        sg.add_conditional_edges(START, dispatch_requirement_reviews, ["requirement_reviewer"])
        # Fan-in via operator.add reducer on requirement_reviews
        sg.add_edge("requirement_reviewer", "hazard_synthesizer")
        sg.add_edge("hazard_synthesizer", END)

        flow = sg.compile(checkpointer=self.checkpointer)
        save_graph_png(flow, Path(settings.log_file_path).parent / "hazard_graph.png")
        return flow
