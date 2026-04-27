import pytest

from autoqa.components.test_case_reviewer.pipeline import TCReviewerRunnable
from autoqa.components.test_case_reviewer.core import (
    TCReviewState,
    Requirement,
    TestCase,
    TestCaseAssessment,
)
from autoqa.components.test_case_reviewer.nodes import load_default_review_objectives
from tests.helpers import load_jsonl, serialize_state


TC_INPUTS = load_jsonl("gold_dataset-tc.jsonl")

REVIEW_OBJECTIVE_IDS = {o.id for o in load_default_review_objectives()}


def _assert_tc_verdict_invariants(asmt: TestCaseAssessment, state: dict) -> None:
    checklist = asmt.evaluated_checklist
    assert len(checklist) == 5, f"expected 5 checklist items, got {len(checklist)}"
    assert {o.id for o in checklist} == REVIEW_OBJECTIVE_IDS, (
        f"checklist ids {sorted(o.id for o in checklist)} != "
        f"review_objectives.yaml ids {sorted(REVIEW_OBJECTIVE_IDS)}"
    )

    for o in checklist:
        if o.verdict == "No":
            assert o.partial is False, (
                f"{o.id}: partial must be False when verdict='No', got True"
            )
        if o.partial:
            assert o.verdict == "Yes", (
                f"{o.id}: partial=True requires verdict='Yes', got {o.verdict!r}"
            )

    expected_overall = "Yes" if all(o.verdict == "Yes" for o in checklist) else "No"
    assert asmt.overall_verdict == expected_overall, (
        f"overall_verdict={asmt.overall_verdict!r} disagrees with AND-across-checklist "
        f"(expected {expected_overall!r}); "
        f"per-objective verdicts={[(o.id, o.verdict) for o in checklist]}"
    )

    cov = {a.spec_id: a.exists for a in state.get("coverage_analysis", [])}
    n_total = len(cov)
    n_covered = sum(1 for v in cov.values() if v is True)
    if n_total == 0:
        expected_sa_verdict, expected_sa_partial = "No", False
    elif n_covered == n_total:
        expected_sa_verdict, expected_sa_partial = "Yes", False
    elif n_covered >= 1:
        expected_sa_verdict, expected_sa_partial = "Yes", True
    else:
        expected_sa_verdict, expected_sa_partial = "No", False

    spec_align = next(
        (o for o in checklist if o.id == "expected_result_spec_align"), None
    )
    assert spec_align is not None, "expected_result_spec_align missing from checklist"
    assert spec_align.verdict == expected_sa_verdict, (
        f"expected_result_spec_align.verdict={spec_align.verdict!r} disagrees with "
        f"count-based tier rule (expected {expected_sa_verdict!r}); "
        f"n_covered={n_covered}/{n_total}, coverage_exists={cov}"
    )
    assert spec_align.partial == expected_sa_partial, (
        f"expected_result_spec_align.partial={spec_align.partial} disagrees with "
        f"count-based tier rule (expected partial={expected_sa_partial}); "
        f"n_covered={n_covered}/{n_total}"
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "tc_input",
    TC_INPUTS,
    ids=[r["test_case"]["test_id"] for r in TC_INPUTS],
)
async def test_tc_pipeline_parametrized(
    real_client, real_model, tc_input, jsonl_recorders_tc
):
    """Run the test_case_reviewer graph for each record in gold_dataset-tc.jsonl.
    Each row carries one test_case + one or more upstream_requirements + the
    designed-intent prediction (expected_overall_verdict, expected_partial_objectives,
    primary_failure). Hard invariants from _assert_tc_verdict_invariants are still
    enforced; the predicted values are attached to the recorded output for post-run
    match-rate analysis (predicted vs LLM-actual)."""
    record_input, record_output = jsonl_recorders_tc
    record_input(tc_input)

    test_case = TestCase(**tc_input["test_case"])
    requirements = [Requirement(**r) for r in tc_input["upstream_requirements"]]
    review_objectives = load_default_review_objectives()

    graph = TCReviewerRunnable(client=real_client, model=real_model)
    result: TCReviewState = await graph.graph.ainvoke(
        {
            "test_case": test_case,
            "requirements": requirements,
            "review_objectives": review_objectives,
        }
    )

    out = serialize_state(result)
    out["expected_overall_verdict"] = tc_input.get("expected_overall_verdict")
    out["expected_partial_objectives"] = tc_input.get("expected_partial_objectives", [])
    out["primary_failure"] = tc_input.get("primary_failure")
    out["fixture_description"] = tc_input.get("description")
    record_output(out)

    asmt = result.get("aggregated_assessment")
    assert isinstance(asmt, TestCaseAssessment), (
        f"aggregated_assessment is {type(asmt).__name__}, not TestCaseAssessment "
        "(aggregator likely skipped due to upstream parse failures)"
    )
    _assert_tc_verdict_invariants(asmt, result)
