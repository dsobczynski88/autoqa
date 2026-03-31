import json
import pytest
from tests.conftest import make_mock_client, load_jsonl
from autoqa.components.rtm_review_agent_medtech.nodes import TestGeneratorNode
from autoqa.components.rtm_review_agent_medtech.core import AITestSuite, DecomposedRequirement, TestSuite

MOCK_RESPONSE = json.dumps({
    "spec_id": "S-001",
    "current_test_suite": [
        {
            "test_case_id": "TC-001",
            "objective": "Verify alert fires above threshold",
            "verifies": "REQ-001",
            "protocol": ["Set reading to 105", "Observe UI"],
            "acceptance_criteria": ["Alert displayed"],
            "is_generated": False,
        }
    ],
    "generated_tests": [
        {
            "test_case_id": "AI-001",
            "objective": "Verify alert at boundary 101 mg/dL",
            "verifies": "REQ-001",
            "protocol": ["Set reading to 101", "Observe UI"],
            "acceptance_criteria": ["Alert displayed"],
            "is_generated": True,
        }
    ],
    "ai_test_suite": [
        {
            "test_case_id": "TC-001",
            "objective": "Verify alert fires above threshold",
            "verifies": "REQ-001",
            "protocol": ["Set reading to 105", "Observe UI"],
            "acceptance_criteria": ["Alert displayed"],
            "is_generated": False,
        },
        {
            "test_case_id": "AI-001",
            "objective": "Verify alert at boundary 101 mg/dL",
            "verifies": "REQ-001",
            "protocol": ["Set reading to 101", "Observe UI"],
            "acceptance_criteria": ["Alert displayed"],
            "is_generated": True,
        },
    ],
    "rationale": "Added boundary test at 101 mg/dL to cover off-by-one scenario.",
})

MARKDOWN_WRAPPED_RESPONSE = f"```json\n{MOCK_RESPONSE}\n```"


@pytest.fixture
def node():
    return TestGeneratorNode(
        client=make_mock_client(MOCK_RESPONSE),
        model="test-model",
        response_model=AITestSuite,
        system_prompt="sys",
    )


def test_validate_state_missing_both(node):
    assert node._validate_state({}) is False


def test_validate_state_missing_test_suite(node, sample_decomposed_requirement):
    assert node._validate_state({"decomposed_requirement": sample_decomposed_requirement}) is False


def test_validate_state_missing_decomposed(node, sample_test_suite):
    assert node._validate_state({"test_suite": sample_test_suite}) is False


def test_validate_state_valid(node, sample_decomposed_requirement, sample_test_suite):
    state = {
        "decomposed_requirement": sample_decomposed_requirement,
        "test_suite": sample_test_suite,
    }
    assert node._validate_state(state) is True


def test_build_payload(node, sample_decomposed_requirement, sample_test_suite):
    state = {
        "decomposed_requirement": sample_decomposed_requirement,
        "test_suite": sample_test_suite,
    }
    payload = node._build_payload(state)
    assert "decomposed_requirement" in payload
    assert "test_suite" in payload


async def test_call_mock_success(node, sample_decomposed_requirement, sample_test_suite):
    state = {
        "decomposed_requirement": sample_decomposed_requirement,
        "test_suite": sample_test_suite,
    }
    result = await node(state)
    assert "ai_test_suite" in result
    assert isinstance(result["ai_test_suite"], AITestSuite)
    assert len(result["ai_test_suite"].generated_tests) == 1


async def test_call_missing_state(node):
    result = await node({})
    assert result == {"ai_test_suite": None}


async def test_call_invalid_json(sample_decomposed_requirement, sample_test_suite):
    bad_node = TestGeneratorNode(
        client=make_mock_client("not json at all"),
        model="test-model",
        response_model=AITestSuite,
        system_prompt="sys",
    )
    state = {
        "decomposed_requirement": sample_decomposed_requirement,
        "test_suite": sample_test_suite,
    }
    result = await bad_node(state)
    assert result == {"ai_test_suite": None}


async def test_call_markdown_wrapped(sample_decomposed_requirement, sample_test_suite):
    node = TestGeneratorNode(
        client=make_mock_client(MARKDOWN_WRAPPED_RESPONSE),
        model="test-model",
        response_model=AITestSuite,
        system_prompt="sys",
    )
    state = {
        "decomposed_requirement": sample_decomposed_requirement,
        "test_suite": sample_test_suite,
    }
    result = await node(state)
    assert "ai_test_suite" in result
    assert isinstance(result["ai_test_suite"], AITestSuite)


_CASES = load_jsonl("generator_cases.jsonl")


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
async def test_call_parametrized(case):
    decomposed = DecomposedRequirement.model_validate(case["input_state"]["decomposed_requirement"])
    test_suite = TestSuite.model_validate(case["input_state"]["test_suite"])
    node = TestGeneratorNode(
        client=make_mock_client(case["mock_response"]),
        model="test-model",
        response_model=AITestSuite,
        system_prompt="sys",
    )
    result = await node({"decomposed_requirement": decomposed, "test_suite": test_suite})
    exp = case["expected"]
    if exp["not_null"]:
        assert result["ai_test_suite"] is not None
        assert len(result["ai_test_suite"].generated_tests) == exp["num_generated"]
    else:
        assert result["ai_test_suite"] is None
