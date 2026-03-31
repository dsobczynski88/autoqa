import pytest
from autoqa.components.rtm_review_agent_medtech.pipeline import RTMReviewerRunnable
from autoqa.components.rtm_review_agent_medtech.core import DecomposedRequirement, TestSuite, EvaluatedSpec


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
