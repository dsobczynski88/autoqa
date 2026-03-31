import json
import os
from pathlib import Path
import pytest
from unittest.mock import MagicMock, AsyncMock

from autoqa.components.clients import RateLimitOpenAIClient
from autoqa.components.rtm_review_agent_medtech.core import (
    Requirement,
    TestCase,
    DecomposedSpec,
    DecomposedRequirement,
    SummarizedTestCase,
    TestSuite,
    EvaluatedSpec,
    AITestSuite,
    AISummarizedTestCase,
)


def load_jsonl(fixture_name: str) -> list[dict]:
    """Load test cases from a JSONL fixture file in tests/fixtures/."""
    path = Path(__file__).parent / "fixtures" / fixture_name
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def make_mock_client(response_content: str) -> RateLimitOpenAIClient:
    """Return a RateLimitOpenAIClient mock whose chat_completion returns response_content."""
    choice = MagicMock()
    choice.message.content = response_content
    completion = MagicMock()
    completion.choices = [choice]
    client = MagicMock(spec=RateLimitOpenAIClient)
    client.chat_completion = AsyncMock(return_value=completion)
    return client


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


@pytest.fixture
def real_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set — skipping integration test")
    return RateLimitOpenAIClient(api_key=api_key)


@pytest.fixture
def real_model():
    return os.getenv("TEST_MODEL", "gpt-4o-mini")
