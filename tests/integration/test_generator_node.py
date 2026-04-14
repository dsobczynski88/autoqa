import pytest
from autoqa.components.test_suite_reviewer.nodes import make_generator_node
from autoqa.components.test_suite_reviewer.core import AITestSuite


@pytest.mark.integration
async def test_generator_node_happy_path(
    real_client, real_model, sample_decomposed_requirement, sample_test_suite
):
    node = make_generator_node(real_client, real_model)
    result = await node({
        "decomposed_requirement": sample_decomposed_requirement,
        "test_suite": sample_test_suite,
    })

    assert result["ai_test_suite"] is not None
    assert isinstance(result["ai_test_suite"], AITestSuite)
    assert len(result["ai_test_suite"].ai_test_suite) > 0
    assert result["ai_test_suite"].spec_id
