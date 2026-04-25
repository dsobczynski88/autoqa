"""
Unit tests for the hazard risk reviewer pipeline.

Each unit test exercises one node or dispatcher in isolation with a mocked
LLM client (HazardSynthesizerNode) or a mocked RTMReviewerRunnable
(RequirementReviewerNode), mirroring the patterns in
tests/unit/test_summary_node.py and test_decomposer_node.py.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoqa.components.hazard_risk_reviewer.core import (
    HazardAssessment,
    HazardFinding,
    HazardRecord,
    RequirementReview,
)
from autoqa.components.hazard_risk_reviewer.nodes import (
    HazardSynthesizerNode,
    RequirementReviewerNode,
    dispatch_requirement_reviews,
)
from autoqa.components.shared.core import Requirement
from autoqa.components.test_suite_reviewer.core import (
    MandatoryFinding,
    SynthesizedAssessment,
)
from tests.helpers import make_mock_client


# Canonical "Adequate" hazard synthesizer response — used as the default mock.
HAZARD_ADEQUATE_RESPONSE = json.dumps({
    "hazard_id": "HAZ-PUMP-001",
    "overall_verdict": "Adequate",
    "mandatory_findings": [
        {
            "code": "H1",
            "dimension": "Hazard Statement Completeness",
            "verdict": "Adequate",
            "rationale": "Hazard, situation, sequence, and harm form a consistent chain.",
            "cited_req_ids": [],
            "cited_test_case_ids": [],
            "unblocked_items": [],
        },
        {
            "code": "H2",
            "dimension": "Pre-Mitigation Risk",
            "verdict": "Adequate",
            "rationale": "Severity Catastrophic and probability Probable yield Unacceptable initial rating.",
            "cited_req_ids": [],
            "cited_test_case_ids": [],
            "unblocked_items": [],
        },
        {
            "code": "H3",
            "dimension": "Risk Control Adequacy",
            "verdict": "Adequate",
            "rationale": "All software causes are controlled by REQ-PUMP-101 and REQ-PUMP-102.",
            "cited_req_ids": ["REQ-PUMP-101", "REQ-PUMP-102"],
            "cited_test_case_ids": [],
            "unblocked_items": [],
        },
        {
            "code": "H4",
            "dimension": "Verification Depth",
            "verdict": "Adequate",
            "rationale": "Fault injection and boundary tests verify the controls.",
            "cited_req_ids": ["REQ-PUMP-101"],
            "cited_test_case_ids": ["TC-PUMP-202", "TC-PUMP-203"],
            "unblocked_items": [],
        },
        {
            "code": "H5",
            "dimension": "Residual Risk Closure",
            "verdict": "Adequate",
            "rationale": "Probability downgrade Probable to Remote is supported by verified controls.",
            "cited_req_ids": [],
            "cited_test_case_ids": [],
            "unblocked_items": [],
        },
    ],
    "comments": "",
    "clarification_questions": [],
})

HAZARD_INADEQUATE_RESPONSE = json.dumps({
    "hazard_id": "HAZ-PUMP-001",
    "overall_verdict": "Inadequate",
    "mandatory_findings": [
        {
            "code": "H1",
            "dimension": "Hazard Statement Completeness",
            "verdict": "Adequate",
            "rationale": "Chain is consistent.",
            "cited_req_ids": [],
            "cited_test_case_ids": [],
            "unblocked_items": [],
        },
        {
            "code": "H2",
            "dimension": "Pre-Mitigation Risk",
            "verdict": "Adequate",
            "rationale": "Risk profile is populated.",
            "cited_req_ids": [],
            "cited_test_case_ids": [],
            "unblocked_items": [],
        },
        {
            "code": "H3",
            "dimension": "Risk Control Adequacy",
            "verdict": "Inadequate",
            "rationale": "No controlling requirement for the scheduler-stall cause.",
            "cited_req_ids": [],
            "cited_test_case_ids": [],
            "unblocked_items": [
                "Scheduler stall under heavy task load"
            ],
        },
        {
            "code": "H4",
            "dimension": "Verification Depth",
            "verdict": "Inadequate",
            "rationale": "Only the functional happy path is exercised.",
            "cited_req_ids": [],
            "cited_test_case_ids": ["TC-PUMP-201"],
            "unblocked_items": [
                "REQ-PUMP-101 watchdog latch behavior"
            ],
        },
        {
            "code": "H5",
            "dimension": "Residual Risk Closure",
            "verdict": "Inadequate",
            "rationale": "Probability downgrade is unsupported by software verification evidence.",
            "cited_req_ids": [],
            "cited_test_case_ids": [],
            "unblocked_items": [],
        },
    ],
    "comments": "Watchdog control claims are not backed by fault-injection tests.",
    "clarification_questions": [
        "Is fault-injection coverage of REQ-PUMP-101 planned in a separate test campaign?",
    ],
})


def _make_mandatory_findings_yes() -> list[MandatoryFinding]:
    """Return five M1-M5 findings, all Yes — used to fabricate a 'good' RTM SynthesizedAssessment."""
    return [
        MandatoryFinding(
            code="M1", dimension="Functional", verdict="Yes",
            rationale="happy path verified", cited_test_case_ids=["TC-PUMP-201"],
        ),
        MandatoryFinding(
            code="M2", dimension="Negative", verdict="Yes",
            rationale="fault injection verified", cited_test_case_ids=["TC-PUMP-202"],
        ),
        MandatoryFinding(
            code="M3", dimension="Boundary", verdict="Yes",
            rationale="boundary verified", cited_test_case_ids=["TC-PUMP-203"],
        ),
        MandatoryFinding(
            code="M4", dimension="Spec Coverage", verdict="Yes",
            rationale="all specs covered",
        ),
        MandatoryFinding(
            code="M5", dimension="Terminology", verdict="Yes",
            rationale="aligned",
        ),
    ]


# --- HazardSynthesizerNode -----------------------------------------------


@pytest.fixture
def hazard_synth_node():
    return HazardSynthesizerNode(
        client=make_mock_client(HAZARD_ADEQUATE_RESPONSE),
        model="test-model",
        response_model=HazardAssessment,
        system_prompt="sys",
    )


def test_synth_validate_state_missing_hazard(hazard_synth_node):
    assert hazard_synth_node._validate_state({}) is False


def test_synth_validate_state_missing_reviews(hazard_synth_node, sample_hazard):
    assert hazard_synth_node._validate_state({"hazard": sample_hazard}) is False


def test_synth_validate_state_empty_reviews(hazard_synth_node, sample_hazard):
    assert hazard_synth_node._validate_state(
        {"hazard": sample_hazard, "requirement_reviews": []}
    ) is False


def test_synth_validate_state_valid(hazard_synth_node, sample_hazard):
    review = RequirementReview(requirement=sample_hazard.requirements[0])
    assert hazard_synth_node._validate_state(
        {"hazard": sample_hazard, "requirement_reviews": [review]}
    ) is True


def test_synth_build_payload(hazard_synth_node, sample_hazard):
    review = RequirementReview(requirement=sample_hazard.requirements[0])
    payload = hazard_synth_node._build_payload(
        {"hazard": sample_hazard, "requirement_reviews": [review]}
    )
    assert payload["hazard"]["hazard_id"] == "HAZ-PUMP-001"
    assert isinstance(payload["requirement_reviews"], list)
    assert len(payload["requirement_reviews"]) == 1
    assert payload["requirement_reviews"][0]["requirement"]["req_id"] == "REQ-PUMP-101"


async def test_synth_call_mock_adequate(hazard_synth_node, sample_hazard):
    review = RequirementReview(requirement=sample_hazard.requirements[0])
    result = await hazard_synth_node(
        {"hazard": sample_hazard, "requirement_reviews": [review]}
    )
    assert "hazard_assessment" in result
    assessment = result["hazard_assessment"]
    assert isinstance(assessment, HazardAssessment)
    assert assessment.hazard_id == "HAZ-PUMP-001"
    assert assessment.overall_verdict == "Adequate"
    assert len(assessment.mandatory_findings) == 5
    assert [f.code for f in assessment.mandatory_findings] == ["H1", "H2", "H3", "H4", "H5"]


async def test_synth_call_mock_inadequate(sample_hazard):
    node = HazardSynthesizerNode(
        client=make_mock_client(HAZARD_INADEQUATE_RESPONSE),
        model="test-model",
        response_model=HazardAssessment,
        system_prompt="sys",
    )
    review = RequirementReview(requirement=sample_hazard.requirements[0])
    result = await node({"hazard": sample_hazard, "requirement_reviews": [review]})
    assessment = result["hazard_assessment"]
    assert assessment.overall_verdict == "Inadequate"
    h3 = next(f for f in assessment.mandatory_findings if f.code == "H3")
    assert h3.verdict == "Inadequate"
    assert h3.unblocked_items == ["Scheduler stall under heavy task load"]


async def test_synth_call_invalid_json(sample_hazard):
    bad_node = HazardSynthesizerNode(
        client=make_mock_client("not json at all"),
        model="test-model",
        response_model=HazardAssessment,
        system_prompt="sys",
    )
    review = RequirementReview(requirement=sample_hazard.requirements[0])
    result = await bad_node(
        {"hazard": sample_hazard, "requirement_reviews": [review]}
    )
    assert result == {"hazard_assessment": None}


async def test_synth_call_skip_when_no_reviews(hazard_synth_node, sample_hazard):
    result = await hazard_synth_node({"hazard": sample_hazard, "requirement_reviews": []})
    assert result == {"hazard_assessment": None}


# --- dispatch_requirement_reviews ----------------------------------------


def test_dispatch_no_hazard():
    sends = dispatch_requirement_reviews({})
    assert sends == []


def test_dispatch_per_requirement(sample_hazard):
    sends = dispatch_requirement_reviews({"hazard": sample_hazard})
    assert len(sends) == len(sample_hazard.requirements)
    for send, req in zip(sends, sample_hazard.requirements):
        assert send.node == "requirement_reviewer"
        assert send.arg["hazard"] is sample_hazard
        assert send.arg["requirement"] is req


# --- RequirementReviewerNode ---------------------------------------------


def _fake_rtm_runnable(rtm_final_state: dict) -> MagicMock:
    """Return a MagicMock that mimics RTMReviewerRunnable.graph.ainvoke."""
    rtm = MagicMock()
    rtm.graph = MagicMock()
    rtm.graph.ainvoke = AsyncMock(return_value=rtm_final_state)
    return rtm


async def test_req_reviewer_happy_path(sample_hazard):
    requirement = sample_hazard.requirements[0]
    rtm_assessment = SynthesizedAssessment(
        requirement=requirement,
        overall_verdict="Yes",
        mandatory_findings=_make_mandatory_findings_yes(),
        comments="",
        clarification_questions=[],
    )
    rtm = _fake_rtm_runnable({
        "synthesized_assessment": rtm_assessment,
        "decomposed_requirement": None,
        "test_suite": None,
        "coverage_analysis": [],
    })
    node = RequirementReviewerNode(rtm)

    result = await node({"hazard": sample_hazard, "requirement": requirement})
    reviews = result["requirement_reviews"]
    assert len(reviews) == 1
    assert reviews[0].requirement.req_id == requirement.req_id
    assert reviews[0].synthesized_assessment.overall_verdict == "Yes"

    # Confirm the wrapped RTM subgraph saw the hazard's test_cases.
    rtm.graph.ainvoke.assert_awaited_once()
    rtm_input = rtm.graph.ainvoke.await_args.args[0]
    assert rtm_input["requirement"] is requirement
    assert rtm_input["test_cases"] == sample_hazard.test_cases


async def test_req_reviewer_subgraph_failure_returns_empty_review(sample_hazard):
    requirement = sample_hazard.requirements[0]
    rtm = MagicMock()
    rtm.graph = MagicMock()
    rtm.graph.ainvoke = AsyncMock(side_effect=RuntimeError("simulated subgraph failure"))
    node = RequirementReviewerNode(rtm)

    result = await node({"hazard": sample_hazard, "requirement": requirement})
    reviews = result["requirement_reviews"]
    assert len(reviews) == 1
    # Even on subgraph failure we record the requirement so the synthesizer
    # has a placeholder rather than silently dropping it.
    assert reviews[0].requirement.req_id == requirement.req_id
    assert reviews[0].synthesized_assessment is None


async def test_req_reviewer_skips_when_payload_incomplete():
    rtm = _fake_rtm_runnable({})
    node = RequirementReviewerNode(rtm)
    result = await node({"hazard": None, "requirement": None})
    assert result == {"requirement_reviews": []}
    rtm.graph.ainvoke.assert_not_awaited()
