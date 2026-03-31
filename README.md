# AutoQA — AI-Powered RTM Reviewer for Medical Device Software

## Background

AutoQA is a software quality tool designed to assist QA engineers and regulatory teams in reviewing Requirements Traceability Matrix (RTM) artifacts for medical device software. Medical device software developed under FDA guidance and the IEC 62304 lifecycle standard must demonstrate that every software requirement is adequately verified by a corresponding test case. In practice, this is a labor-intensive review process prone to coverage gaps, inconsistent rationale, and missed edge cases. AutoQA automates the analytical layer of that review by accepting a software requirement alongside its associated test suite and producing a structured coverage verdict (scored 0 to 5 per atomic specification) complete with cited test cases and written rationale.

Under the hood, AutoQA uses a four-node LangGraph pipeline to break a requirement into its testable atomic specifications (functional, boundary, safety, performance), semantically summarize each test case in the suite, generate adversarial gap-filling tests for underserved specifications, and finally evaluate per-spec coverage against the full test suite. The result is a machine-generated coverage analysis that surfaces gaps, flags weak coverage, and provides a transparent audit trail — the kind of traceability evidence that supports FDA submissions and IEC 62304 compliance reviews.

---

## Getting Started

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) package manager
- An OpenAI API key (Ollama and AWS Bedrock are also supported as alternative backends)

### Installation

```bash
git clone <repo-url>
cd autoqa-feature-initial-prototype
uv sync --frozen
```

### Environment Setup

Create a `.env` file in the repo root and populate your credentials:

```env
# Required
OPENAI_API_KEY=sk-...

# Optional — defaults shown
MODEL=gpt-4o
MAX_REQUESTS_PER_MINUTE=490
MAX_TOKENS_PER_MINUTE=200000
```

---

## Running Tests

```bash
# Unit tests (no API key required — all LLM calls are mocked)
uv run pytest tests/unit/ -v

# Integration tests (requires a live OPENAI_API_KEY in .env)
uv run pytest -m integration -v
```

The unit test suite covers all four pipeline nodes with both plain-JSON and markdown-wrapped LLM response variants. JSONL fixture files in `tests/fixtures/` make it easy to add new test scenarios without changing any Python — append a line to the relevant file and it is automatically picked up by `@pytest.mark.parametrize`.

---

## API Usage

### Starting the Server

```bash
uv run uvicorn autoqa.api.main:app --reload
```

The interactive API documentation is available at `http://localhost:8000/docs` once the server is running.

### Endpoint Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/review` | Submit a requirement and test suite for RTM coverage analysis |

### Quickstart: curl

```bash
curl -X POST http://localhost:8000/api/v1/review \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "review-session-001",
    "requirement": {
      "req_id": "SRS-042",
      "text": "The system shall generate an audible and visual alarm within 5 seconds when the measured glucose concentration exceeds the user-configured high threshold."
    },
    "test_cases": [
      {
        "test_id": "TC-101",
        "description": "Verify high-glucose alarm activation",
        "setup": "Device powered on, high threshold set to 180 mg/dL",
        "steps": "Simulate glucose reading of 200 mg/dL via test fixture",
        "expectedResults": "Audible alarm sounds and alert banner displayed within 5 seconds"
      },
      {
        "test_id": "TC-102",
        "description": "Verify no alarm fires when reading is below threshold",
        "setup": "Device powered on, high threshold set to 180 mg/dL",
        "steps": "Simulate glucose reading of 150 mg/dL",
        "expectedResults": "No alarm triggered"
      }
    ]
  }'
```

**Example response:**

```json
{
  "status": "completed",
  "thread_id": "review-session-001",
  "coverage_analysis": [
    {
      "spec_id": "S-001",
      "covered_exists": true,
      "covered_extent": 4,
      "covered_by_test_cases": ["TC-101"],
      "coverage_rationale": "TC-101 directly verifies the alarm fires above the configured threshold within the required 5-second window. Coverage is strong but does not test the exact boundary value (180 mg/dL) or alarm latency at the lower edge of the timing window."
    }
  ],
  "decomposed_requirement": {},
  "test_suite": {}
}
```

### Quickstart: Python

```python
import asyncio
import httpx

payload = {
    "thread_id": "review-session-001",
    "requirement": {
        "req_id": "SRS-042",
        "text": "The system shall generate an audible and visual alarm within 5 seconds when the measured glucose concentration exceeds the user-configured high threshold."
    },
    "test_cases": [
        {
            "test_id": "TC-101",
            "description": "Verify high-glucose alarm activation",
            "setup": "Device powered on, high threshold set to 180 mg/dL",
            "steps": "Simulate glucose reading of 200 mg/dL via test fixture",
            "expectedResults": "Audible alarm sounds and alert banner displayed within 5 seconds"
        }
    ]
}

async def main():
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            "http://localhost:8000/api/v1/review",
            json=payload,
        )
        result = response.json()

    for spec in result["coverage_analysis"]:
        print(f"[{spec['spec_id']}] Score: {spec['covered_extent']}/5")
        print(f"  Covered by: {spec['covered_by_test_cases']}")
        print(f"  Rationale:  {spec['coverage_rationale']}\n")

asyncio.run(main())
```

---

## Current Work

AutoQA is under active development. The following capabilities are on the near-term roadmap:

**Individual test case reviews** — In addition to per-specification coverage scoring, a planned node will provide a deep-dive review of each individual test case: assessing completeness, checking for ambiguous pass/fail criteria, and flagging test cases that do not satisfy IEC 62304 traceability requirements.

**Additional medical device document types** — The review pipeline will be extended beyond RTM artifacts to support other regulatory and quality documents common in medical device software development, including Software Requirements Specifications (SRS), risk management files per ISO 14971, and records of Software of Unknown Provenance (SOUP).

**Persistent thread state** — The current implementation uses an in-memory checkpointer, meaning thread history is lost on server restart. A database-backed checkpointer (SQLite or PostgreSQL) is planned to support long-running review sessions and audit trail preservation.

**Batch review endpoint** — A `POST /api/v1/batch-review` endpoint is planned to accept a full RTM table (multiple requirements and their associated test cases) and run the pipeline concurrently, returning a consolidated coverage report suitable for regulatory submission packages.
