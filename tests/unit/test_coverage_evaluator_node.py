import json
import pytest
from tests.helpers import make_mock_client, load_jsonl
from autoqa.components.rtm_review_agent_medtech.nodes import CoverageEvaluatorNode
from autoqa.components.rtm_review_agent_medtech.core import EvaluatedSpec, Requirement, DecomposedRequirement, TestSuite

MOCK_EVAL_RESPONSE = json.dumps({
    "spec_id": "S-001",
    "covered_exists": True,
    "covered_extent": 4,
    "covered_by_test_cases": ["TC-001"],
    "coverage_rationale": "TC-001 directly verifies the alert fires above threshold.",
})

MARKDOWN_WRAPPED_RESPONSE = f"```json\n{MOCK_EVAL_RESPONSE}\n```"


@pytest.fixture
def node():
    return CoverageEvaluatorNode(
        client=make_mock_client(MOCK_EVAL_RESPONSE),
        model="test-model",
        system_prompt="sys",
    )


def test_validate_state_empty(node):
    assert node._validate_state({}) is False


def test_validate_state_missing_test_suite(node, sample_requirement, sample_decomposed_requirement):
    state = {
        "requirement": sample_requirement,
        "decomposed_requirement": sample_decomposed_requirement,
    }
    assert node._validate_state(state) is False


def test_validate_state_missing_decomposed(node, sample_requirement, sample_test_suite):
    state = {
        "requirement": sample_requirement,
        "test_suite": sample_test_suite,
    }
    assert node._validate_state(state) is False


def test_validate_state_valid(node, sample_requirement, sample_decomposed_requirement, sample_test_suite):
    state = {
        "requirement": sample_requirement,
        "decomposed_requirement": sample_decomposed_requirement,
        "test_suite": sample_test_suite,
    }
    assert node._validate_state(state) is True


async def test_call_missing_state(node):
    result = await node({})
    assert result == {"coverage_analysis": []}


async def test_call_mock_success(node, sample_requirement, sample_decomposed_requirement, sample_test_suite):
    state = {
        "requirement": sample_requirement,
        "decomposed_requirement": sample_decomposed_requirement,
        "test_suite": sample_test_suite,
    }
    result = await node(state)
    assert "coverage_analysis" in result
    assert len(result["coverage_analysis"]) > 0
    assert all(isinstance(e, EvaluatedSpec) for e in result["coverage_analysis"])


async def test_call_mock_multiple_specs(sample_requirement, sample_decomposed_requirement, sample_test_suite):
    """Each spec generates one LLM call; all specs should produce an EvaluatedSpec."""
    node = CoverageEvaluatorNode(
        client=make_mock_client(MOCK_EVAL_RESPONSE),
        model="test-model",
        system_prompt="sys",
    )
    state = {
        "requirement": sample_requirement,
        "decomposed_requirement": sample_decomposed_requirement,
        "test_suite": sample_test_suite,
    }
    result = await node(state)
    assert "coverage_analysis" in result
    assert len(result["coverage_analysis"]) == len(sample_decomposed_requirement.decomposed_specifications)


async def test_call_invalid_json(sample_requirement, sample_decomposed_requirement, sample_test_suite):
    bad_node = CoverageEvaluatorNode(
        client=make_mock_client("not json at all"),
        model="test-model",
        system_prompt="sys",
    )
    state = {
        "requirement": sample_requirement,
        "decomposed_requirement": sample_decomposed_requirement,
        "test_suite": sample_test_suite,
    }
    result = await bad_node(state)
    assert result == {"coverage_analysis": []}


async def test_call_markdown_wrapped(sample_requirement, sample_decomposed_requirement, sample_test_suite):
    node = CoverageEvaluatorNode(
        client=make_mock_client(MARKDOWN_WRAPPED_RESPONSE),
        model="test-model",
        system_prompt="sys",
    )
    state = {
        "requirement": sample_requirement,
        "decomposed_requirement": sample_decomposed_requirement,
        "test_suite": sample_test_suite,
    }
    result = await node(state)
    assert "coverage_analysis" in result
    assert len(result["coverage_analysis"]) == len(sample_decomposed_requirement.decomposed_specifications)
    assert all(isinstance(e, EvaluatedSpec) for e in result["coverage_analysis"])


_CASES = load_jsonl("coverage_evaluator_cases.jsonl")


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
async def test_call_parametrized(case):
    requirement = Requirement.model_validate(case["input_state"]["requirement"])
    decomposed = DecomposedRequirement.model_validate(case["input_state"]["decomposed_requirement"])
    test_suite = TestSuite.model_validate(case["input_state"]["test_suite"])
    node = CoverageEvaluatorNode(
        client=make_mock_client(case["mock_response"]),
        model="test-model",
        system_prompt="sys",
    )
    state = {
        "requirement": requirement,
        "decomposed_requirement": decomposed,
        "test_suite": test_suite,
    }
    result = await node(state)
    assert len(result["coverage_analysis"]) == case["expected"]["num_evaluated"]
    assert all(isinstance(e, EvaluatedSpec) for e in result["coverage_analysis"])
