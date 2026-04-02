"""
Node implementations for RTM review agent.

1. State validation
2. Payload building
3. LLM invocation with error handling
4. Response formatting

Class hierarchy:
- BaseLLMNode(ABC): true base — config, static utilities (_extract_json_from_markdown,
  _parse_llm_response), abstract _validate_state
- StandardLLMNode(BaseLLMNode, ABC): single-call Template Method — adds response_model,
  abstract _build_payload/_format_response, concrete __call__
- DecomposerNode, SummaryNode, TestGeneratorNode: extend StandardLLMNode
- CoverageEvaluatorNode: extends BaseLLMNode directly (N sequential LLM calls, no
  _build_payload/_format_response contract)
"""
import json
import re
from typing import Optional, List, Dict, Any
from abc import ABC, abstractmethod
from autoqa.components.clients import RateLimitOpenAIClient
from autoqa.utils import render_prompt
from autoqa.prj_logger import ProjectLogger
from autoqa.core.config import settings

project_logger = ProjectLogger(name="logger.nodes", log_file=settings.log_file_path)
project_logger.config()
logger = project_logger.get_logger()
from .core import (
    RTMReviewState,
    Requirement,
    DecomposedRequirement,
    TestCase,
    TestSuite,
    EvaluatedSpec,
    ReviewComment,
    AITestSuite
)


class BaseLLMNode(ABC):
    """
    True base class for all LLM-powered nodes. Holds shared config and utilities.
    Does NOT impose the single-call Template Method — that lives in StandardLLMNode.
    """

    def __init__(self, client: RateLimitOpenAIClient, model: str, system_prompt: str, model_kwargs: dict = None):
        self.client = client
        self.model = model
        self.system_prompt = system_prompt
        self.model_kwargs = model_kwargs or {}

    @abstractmethod
    def _validate_state(self, state: Dict) -> bool:
        """Return True if required state keys are present and non-None."""
        pass

    @staticmethod
    def _extract_json_from_markdown(text: str) -> str:
        """
        Extract JSON from markdown code fences if present, otherwise
        slice from the first '{' or '[' to the end.
        """
        fence = re.search(r"```(?:json|jsonc|javascript|js)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if fence:
            return fence.group(1).strip()
        first_brace = text.find("{")
        first_bracket = text.find("[")
        starts = [i for i in (first_brace, first_bracket) if i != -1]
        if starts:
            return text[min(starts):].strip()
        return text.strip()

    @staticmethod
    def _parse_llm_response(result, response_model, node_name: str = "") -> Optional[Any]:
        """Try each choice in the LLM result; return the first successfully parsed model."""
        for choice in result.choices:
            try:
                content = choice.message.content
                logger.debug("%s: raw LLM response — %s", node_name, content)
                extracted_json = BaseLLMNode._extract_json_from_markdown(content)
                try:
                    return response_model.model_validate_json(extracted_json)
                except Exception:
                    py_obj = json.loads(extracted_json)
                    return response_model.model_validate(py_obj)
            except Exception as e:
                logger.warning("%s: parse failed for choice — %s", node_name, e)
                continue
        return None


class StandardLLMNode(BaseLLMNode, ABC):
    """
    Single-call Template Method node. Subclasses implement _build_payload and
    _format_response; __call__ orchestrates the full flow.
    """

    def __init__(self, client: RateLimitOpenAIClient, model: str, response_model, system_prompt: str, model_kwargs: dict = None):
        super().__init__(client, model, system_prompt, model_kwargs)
        self.response_model = response_model

    @abstractmethod
    def _build_payload(self, state: Dict) -> Any:
        """Build the payload to send to the LLM from the state."""
        pass

    @abstractmethod
    def _format_response(self, parsed_result: Any) -> Dict:
        """Format the parsed LLM result into a state-update dict."""
        pass

    def _get_skip_response(self) -> Dict:
        return {}

    async def __call__(self, state: Dict) -> Dict:
        if not self._validate_state(state):
            logger.debug("%s: skipping — validation failed", self.__class__.__name__)
            return self._get_skip_response()

        try:
            payload = self._build_payload(state)
        except Exception as e:
            logger.warning("%s: payload building failed — %s", self.__class__.__name__, e)
            return self._get_skip_response()

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": json.dumps(payload)},
        ]

        result = await self.client.chat_completion(
            model=self.model,
            messages=messages,
            **self.model_kwargs,
        )
        parsed = self._parse_llm_response(result, self.response_model, self.__class__.__name__)

        if parsed is None:
            logger.warning("%s: all choices failed to parse, returning skip response", self.__class__.__name__)
            return self._get_skip_response()

        return self._format_response(parsed)


class DecomposerNode(StandardLLMNode):
    """Decomposes high-level requirements into atomic specifications."""

    def _validate_state(self, state: Dict) -> bool:
        return state.get("requirement") is not None

    def _build_payload(self, state: Dict) -> dict:
        requirement = state["requirement"]
        return {
            "requirement_id": requirement.req_id,
            "requirement": requirement.text,
        }

    def _format_response(self, parsed_result: Optional[DecomposedRequirement]) -> Dict:
        return {"decomposed_requirement": parsed_result}

    def _get_skip_response(self) -> Dict:
        return {"decomposed_requirement": None}


class SummaryNode(StandardLLMNode):
    """Summarizes raw test cases into structured format."""

    def _validate_state(self, state: Dict) -> bool:
        return state.get("test_cases") is not None

    def _build_payload(self, state: Dict) -> list:
        test_cases = state["test_cases"]
        return [
            {
                "test_id": tc.test_id,
                "description": tc.description,
                "setup": tc.setup,
                "steps": tc.steps,
                "expectedResults": tc.expectedResults
            }
            for tc in test_cases
        ]

    def _format_response(self, parsed_result: Optional[TestSuite]) -> Dict:
        return {"test_suite": parsed_result}

    def _get_skip_response(self) -> Dict:
        return {"test_suite": None}

class CoverageEvaluatorNode(BaseLLMNode):
    """Evaluates test coverage for each decomposed spec individually (N sequential LLM calls)."""

    def __init__(self, client: RateLimitOpenAIClient, model: str, system_prompt: str, model_kwargs: dict = None):
        super().__init__(client, model, system_prompt, model_kwargs)

    def _validate_state(self, state: Dict) -> bool:
        requirement = state.get("requirement")
        decomposed = state.get("decomposed_requirement")
        test_suite = state.get("test_suite")
        return all([requirement is not None, decomposed is not None, test_suite is not None])

    async def __call__(self, state: Dict) -> Dict:
        if not self._validate_state(state):
            logger.debug("%s: skipping — validation failed", self.__class__.__name__)
            return {"coverage_analysis": []}

        requirement = state["requirement"]
        decomposed = state["decomposed_requirement"]
        test_suite = state["test_suite"]

        evaluated_specs: List[EvaluatedSpec] = []

        for spec in decomposed.decomposed_specifications:
            payload = {
                "original_requirement": requirement.model_dump(),
                "decomposed_spec": spec.model_dump(),
                "test_suite": test_suite.model_dump(),
            }

            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": json.dumps(payload)},
            ]

            result = await self.client.chat_completion(
                model=self.model,
                messages=messages,
                **self.model_kwargs,
            )
            parsed = self._parse_llm_response(result, EvaluatedSpec, self.__class__.__name__)
            if parsed:
                evaluated_specs.append(parsed)

        return {"coverage_analysis": evaluated_specs} if evaluated_specs else {"coverage_analysis": []}


class TestGeneratorNode(StandardLLMNode):
    """Generates adversarial test cases to fill coverage gaps."""

    def _validate_state(self, state: Dict) -> bool:
        decomposed = state.get("decomposed_requirement")
        test_suite = state.get("test_suite")
        return decomposed is not None and test_suite is not None

    def _build_payload(self, state: Dict) -> dict:
        return {
            "decomposed_requirement": state["decomposed_requirement"].model_dump(),
            "test_suite": state["test_suite"].model_dump(),
        }

    def _format_response(self, parsed_result: Optional[AITestSuite]) -> Dict:
        return {"ai_test_suite": parsed_result}

    def _get_skip_response(self) -> Dict:
        return {"ai_test_suite": None}


# Factory functions remain largely the same but instantiate the refactored classes

def make_decomposer_node(client: RateLimitOpenAIClient, model: str, **template_vars) -> DecomposerNode:
    """
    Create a DecomposerNode with prompt loaded from Jinja2 template.

    Args:
        client: RateLimitOpenAIClient instance
        model: Model identifier string
        **template_vars: Optional variables to pass to the Jinja2 template

    Returns:
        DecomposerNode: Configured decomposer node
    """
    system_prompt = render_prompt('decomposer-v2.jinja2', **template_vars)
    return DecomposerNode(
        client=client,
        model=model,
        response_model=DecomposedRequirement,
        system_prompt=system_prompt,
    )


def make_summarizer_node(client: RateLimitOpenAIClient, model: str, **template_vars) -> SummaryNode:
    """
    Create a SummaryNode with prompt loaded from Jinja2 template.

    Args:
        client: RateLimitOpenAIClient instance
        model: Model identifier string
        **template_vars: Optional variables to pass to the Jinja2 template

    Returns:
        SummaryNode: Configured summarizer node
    """
    system_prompt = render_prompt('summarizer-v2.jinja2', **template_vars)
    return SummaryNode(
        client=client,
        model=model,
        response_model=TestSuite,
        system_prompt=system_prompt,
    )


def make_generator_node(client: RateLimitOpenAIClient, model: str, **template_vars) -> TestGeneratorNode:
    """
    Create a TestGeneratorNode with prompt loaded from Jinja2 template.

    Args:
        client: RateLimitOpenAIClient instance
        model: Model identifier string
        **template_vars: Optional variables to pass to the Jinja2 template

    Returns:
        TestGeneratorNode: Configured test generator node
    """
    system_prompt = render_prompt('test_generator.jinja2', **template_vars)
    return TestGeneratorNode(
        client=client,
        model=model,
        response_model=AITestSuite,
        system_prompt=system_prompt,
    )


def make_coverage_evaluator(client: RateLimitOpenAIClient, model: str, **template_vars) -> CoverageEvaluatorNode:
    """
    Create a CoverageEvaluatorNode that evaluates each decomposed spec individually.

    The node uses coverage_evaluator-v3.jinja2 template which expects:
    - requirement_data: The original requirement
    - decomposed_spec: A single decomposed specification
    - test_suite: List of summarized test cases
    - project_context: Optional project-specific context

    Args:
        client: RateLimitOpenAIClient instance
        model: Model identifier string
        **template_vars: Optional variables to pass to the Jinja2 template

    Returns:
        CoverageEvaluatorNode: Configured coverage evaluator node that processes
                                       each spec individually and returns CoverageEvaluator
    """
    system_prompt = render_prompt('coverage_evaluator-v4.jinja2', **template_vars)
    return CoverageEvaluatorNode(
        client=client,
        model=model,
        system_prompt=system_prompt,
    )


def make_aggregator_node(client: RateLimitOpenAIClient, model: str) -> Dict:
    pass
