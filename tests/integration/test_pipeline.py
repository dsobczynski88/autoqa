import json
import pytest
from pathlib import Path
from autoqa.core.config import settings
from autoqa.components.rtm_review_agent_medtech.pipeline import RTMReviewerRunnable
from autoqa.components.rtm_review_agent_medtech.core import (
    RTMReviewState, Requirement, TestCase, DecomposedRequirement, TestSuite,
    EvaluatedSpec, SynthesizedAssessment,
)
from tests.helpers import load_jsonl, serialize_state

PIPELINE_INPUTS = load_jsonl("hc_pipeline_inputs.jsonl")


@pytest.mark.integration
async def test_pipeline_decomposer_node(real_client, real_model, sample_requirement, sample_test_cases):
    """Run the full pipeline and verify the decomposer produced structured output."""
    graph = RTMReviewerRunnable(client=real_client, model=real_model)
    state = {"requirement": sample_requirement, "test_cases": sample_test_cases}
    result = await graph.graph.ainvoke(state)

    assert result.get("decomposed_requirement") is not None
    assert isinstance(result["decomposed_requirement"], DecomposedRequirement)
    specs = result["decomposed_requirement"].decomposed_specifications
    assert len(specs) > 0
    print(f"\n[decomposer] {len(specs)} specs generated")
    for s in specs:
        print(f"  {s.spec_id}: {s.description[:60]}")


@pytest.mark.integration
async def test_pipeline_summarizer_node(real_client, real_model, sample_requirement, sample_test_cases):
    """Verify summarizer produced a structured TestSuite."""
    graph = RTMReviewerRunnable(client=real_client, model=real_model)
    state = {"requirement": sample_requirement, "test_cases": sample_test_cases}
    result = await graph.graph.ainvoke(state)

    assert result.get("test_suite") is not None
    assert isinstance(result["test_suite"], TestSuite)
    assert len(result["test_suite"].summary) > 0
    print(f"\n[summarizer] {len(result['test_suite'].summary)} summaries produced")


@pytest.mark.integration
async def test_pipeline_coverage_node(real_client, real_model, sample_requirement, sample_test_cases):
    """Verify coverage evaluator produced EvaluatedSpec results."""
    graph = RTMReviewerRunnable(client=real_client, model=real_model)
    state = {"requirement": sample_requirement, "test_cases": sample_test_cases}
    result = await graph.graph.ainvoke(state)

    evals = result.get("coverage_analysis", [])
    assert len(evals) > 0
    assert all(isinstance(e, EvaluatedSpec) for e in evals)
    print(f"\n[coverage] {len(evals)} specs evaluated")
    for e in evals:
        print(f"  {e.spec_id}: covered={e.covered_exists}, extent={e.covered_extent}/5")
        print(f"  rationale: {e.coverage_rationale[:80]}")


@pytest.mark.integration
async def test_pipeline_full_state(real_client, real_model, sample_requirement, sample_test_cases):
    """Run the full pipeline, validate all RTMReviewState fields, and save state as JSON."""
    graph = RTMReviewerRunnable(client=real_client, model=real_model)
    initial_state = {"requirement": sample_requirement, "test_cases": sample_test_cases}
    result: RTMReviewState = await graph.graph.ainvoke(initial_state)

    assert isinstance(result.get("requirement"), Requirement)
    assert isinstance(result.get("test_cases"), list) and len(result["test_cases"]) > 0
    assert isinstance(result.get("decomposed_requirement"), DecomposedRequirement)
    assert len(result["decomposed_requirement"].decomposed_specifications) > 0
    assert isinstance(result.get("test_suite"), TestSuite)
    assert len(result["test_suite"].summary) > 0
    evals = result.get("coverage_analysis", [])
    assert len(evals) == len(result["decomposed_requirement"].decomposed_specifications)
    assert all(isinstance(e, EvaluatedSpec) for e in evals)

    output_path = Path(settings.log_file_path).parent / "pipeline_state.json"
    output_path.write_text(json.dumps(serialize_state(result), indent=2))
    print(f"\n[full_state] saved → {output_path}")


@pytest.mark.integration
@pytest.mark.parametrize(
    "pipeline_input",
    PIPELINE_INPUTS,
    ids=[r["requirement"]["req_id"] for r in PIPELINE_INPUTS],
)
async def test_pipeline_parametrized(real_client, real_model, pipeline_input, jsonl_recorders):
    """Runs the full pipeline for each HC input record and records inputs/outputs to JSONL."""
    record_input, record_output = jsonl_recorders

    # Write full input record (including rationale) for traceability
    record_input(pipeline_input)

    requirement = Requirement(**pipeline_input["requirement"])
    test_cases = [TestCase(**tc) for tc in pipeline_input["test_cases"]]

    graph = RTMReviewerRunnable(client=real_client, model=real_model)
    result: RTMReviewState = await graph.graph.ainvoke(
        {"requirement": requirement, "test_cases": test_cases}
    )

    assert isinstance(result.get("decomposed_requirement"), DecomposedRequirement)
    assert isinstance(result.get("test_suite"), TestSuite)
    evals = result.get("coverage_analysis", [])
    assert len(evals) > 0
    assert all(isinstance(e, EvaluatedSpec) for e in evals)
    assert isinstance(result.get("synthesized_assessment"), SynthesizedAssessment)

    record_output(serialize_state(result))
