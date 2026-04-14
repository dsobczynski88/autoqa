import json
import os
from pathlib import Path
import pytest
from dotenv import load_dotenv
load_dotenv()
from autoqa.core.config import settings

from autoqa.components.clients import RateLimitOpenAIClient
from autoqa.components.test_suite_reviewer.core import (
    Requirement,
    TestCase,
    DecomposedSpec,
    DecomposedRequirement,
    SummarizedTestCase,
    TestSuite,
    EvaluatedSpec,
)

@pytest.fixture
def sample_requirement():
    return Requirement(
        req_id="REQ-001",
        text="The system shall display an alert when sensor reading exceeds 100 mg/dL.",
    )

@pytest.fixture
def sample_test_cases():
    return [
        TestCase(
            test_id="TC-001",
            description="Verify alert fires above threshold",
            setup="Sensor connected",
            steps="Set reading to 105",
            expectedResults="Alert displayed",
        ),
        TestCase(
            test_id="TC-002",
            description="Verify no alert below threshold",
            setup="Sensor connected",
            steps="Set reading to 95",
            expectedResults="No alert",
        ),
    ]


@pytest.fixture
def sample_decomposed_requirement(sample_requirement):
    specs = [
        DecomposedSpec(
            spec_id="S-001",
            type="Functional",
            description="Alert fires when reading > 100 mg/dL",
            acceptance_criteria="Alert visible within 1s",
            rationale="Happy path",
        ),
        DecomposedSpec(
            spec_id="S-002",
            type="Boundary",
            description="No alert when reading <= 100 mg/dL",
            acceptance_criteria="No alert at exactly 100 mg/dL",
            rationale="Boundary",
        ),
    ]
    return DecomposedRequirement(
        requirement=sample_requirement,
        decomposed_specifications=specs,
    )


@pytest.fixture
def sample_test_suite(sample_requirement, sample_test_cases):
    summaries = [
        SummarizedTestCase(
            test_case_id="TC-001",
            objective="Verify alert above threshold",
            verifies="REQ-001",
            protocol=["Set reading to 105", "Check UI for alert"],
            acceptance_criteria=["Alert shown within 1s"],
        ),
        SummarizedTestCase(
            test_case_id="TC-002",
            objective="Verify no alert below threshold",
            verifies="REQ-001",
            protocol=["Set reading to 95", "Check UI"],
            acceptance_criteria=["No alert displayed"],
        ),
    ]
    return TestSuite(
        requirement=sample_requirement,
        test_cases=sample_test_cases,
        summary=summaries,
    )


@pytest.fixture(scope="session")
def jsonl_recorders():
    """Session-scoped fixture that clears inputs.jsonl / outputs.jsonl once at session
    start, then yields (record_input, record_output) append functions."""
    run_dir = Path(settings.log_file_path).parent
    inputs_path = run_dir / "inputs.jsonl"
    outputs_path = run_dir / "outputs.jsonl"
    inputs_path.write_text("", encoding="utf-8")
    outputs_path.write_text("", encoding="utf-8")

    def record_input(data: dict) -> None:
        with inputs_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")

    def record_output(data: dict) -> None:
        with outputs_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")

    yield record_input, record_output


@pytest.fixture
def real_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set — skipping integration test")
    return RateLimitOpenAIClient(api_key=api_key)


@pytest.fixture
def real_model():
    return os.getenv("TEST_MODEL", "gpt-4o-mini")