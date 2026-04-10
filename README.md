# AutoQA — AI-Powered RTM Reviewer for Medical Device Software

## Background

AutoQA is a software quality tool designed to assist QA engineers and regulatory teams in reviewing Requirements Traceability Matrix (RTM) artifacts for medical device software. Medical device software developed under FDA guidance and the IEC 62304 lifecycle standard must demonstrate that every software requirement is adequately verified by a corresponding test case. In practice, this is a labor-intensive review process prone to coverage gaps, inconsistent rationale, and missed edge cases. AutoQA automates the analytical layer of that review by accepting a software requirement alongside its associated test suite and producing a structured coverage verdict (scored 0 to 5 per atomic specification) complete with cited test cases, written rationale, and a synthesized holistic assessment.

---

## Pipeline Architecture

AutoQA uses a five-node LangGraph pipeline. Nodes run with maximum parallelism: the decomposer and summarizer execute concurrently from `START`, and each decomposed specification is evaluated by a dedicated evaluator node running in parallel via LangGraph's `Send` API.

```
START
  ↓
┌──────────────────────────────────────┐
│ DECOMPOSER       SUMMARIZER          │  ← parallel
│ Breaks requirement into atomic specs │  ← structures raw test cases
└──────────────────────────────────────┘
  ↓ (fan-in)
┌──────────────────────────────────────┐
│ COVERAGE_ROUTER  (sync point)        │
└──────────────────────────────────────┘
  ↓ Send × N (one per decomposed spec)
┌──────────────────────────────────────┐
│ SPEC_EVALUATOR × N  (parallel)       │  ← one LLM call per spec
└──────────────────────────────────────┘
  ↓ (fan-in: operator.add accumulates coverage_analysis)
┌──────────────────────────────────────┐
│ SYNTHESIZER  (MoA-inspired)          │  ← holistic assessment across all specs
└──────────────────────────────────────┘
  ↓
END
```

Each pipeline run also writes a Mermaid graph diagram (`graph.png`) to the run's log folder alongside `autoqa.log`.

### Output fields

| Field | Description |
|-------|-------------|
| `decomposed_requirement` | Requirement broken into typed atomic specs (functional, boundary, negative, etc.) |
| `test_suite` | Structured summary of each test case — objective, protocol, acceptance criteria |
| `coverage_analysis` | Per-spec verdict: `covered_exists`, `covered_extent` (0–5), cited test case IDs, and rationale |
| `synthesized_assessment` | MoA-synthesized view across functional, negative, and boundary/edge perspectives with gap recommendations |

---

## Getting Started

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) package manager
- An OpenAI API key

### Installation

```bash
git clone <repo-url>
cd autoqa
uv sync --frozen
```

### Environment Setup

Create a `.env` file in the repo root:

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

# Parameterized batch run — 10 HC requirement records, records inputs.jsonl + outputs.jsonl
uv run pytest tests/integration/test_pipeline.py::test_pipeline_parametrized -m integration -s

uv run pytest tests/integration/test_pipeline.py::test_pipeline_parametrized_standard_coverage -m integration -s

uv run pytest tests/integration/test_pipeline.py::test_pipeline_parametrized_advanced_coverage -m integration -s
```

The unit test suite covers all pipeline nodes with both plain-JSON and markdown-wrapped LLM response variants. JSONL fixture files in `tests/fixtures/` make it easy to add new test scenarios — append a line to the relevant file and it is automatically picked up by `@pytest.mark.parametrize`.

The integration test suite includes a session-scoped `jsonl_recorders` fixture that writes `inputs.jsonl` and `outputs.jsonl` to the active `logs/run-.../` folder, enabling offline analysis of model outputs across a batch of requirements.

All run artifacts are written to a timestamped `logs/run-<datetime>/` directory:

| File | Contents |
|------|----------|
| `autoqa.log` | Structured application logs |
| `graph.png` | Mermaid diagram of the compiled LangGraph |
| `pipeline_state.json` | Full serialized state from a single pipeline run |
| `inputs.jsonl` | Input records fed to the parametrized test |
| `outputs.jsonl` | Serialized pipeline state for each parametrized run |

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
  "test_suite": {},
  "synthesized_assessment": {
    "requirement": {"req_id": "SRS-042", "text": "..."},
    "coverage_assessment": "Functional coverage is present via TC-101 and TC-102. Boundary coverage is absent — no test exercises the exact threshold value of 180 mg/dL. Negative coverage is partially addressed by TC-102.",
    "comments": "Add a boundary test at exactly 180 mg/dL. Add a test verifying alarm latency is within the 5-second window under load conditions."
  }
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

    assessment = result.get("synthesized_assessment", {})
    print("Synthesized Assessment:")
    print(assessment.get("coverage_assessment"))
    print("\nRecommendations:")
    print(assessment.get("comments"))

asyncio.run(main())
```

---

## Current Work

AutoQA is under active development. The following capabilities are on the near-term roadmap:

**Individual test case reviews** — In addition to per-specification coverage scoring, a planned node will provide a deep-dive review of each individual test case: assessing completeness, checking for ambiguous pass/fail criteria, and flagging test cases that do not satisfy IEC 62304 traceability requirements.

**Additional medical device document types** — The review pipeline will be extended beyond RTM artifacts to support other regulatory and quality documents common in medical device software development, including Software Requirements Specifications (SRS), risk management files per ISO 14971, and records of Software of Unknown Provenance (SOUP).

**Persistent thread state** — The current implementation uses an in-memory checkpointer, meaning thread history is lost on server restart. A database-backed checkpointer (SQLite or PostgreSQL) is planned to support long-running review sessions and audit trail preservation.

**Batch review endpoint** — A `POST /api/v1/batch-review` endpoint is planned to accept a full RTM table (multiple requirements and their associated test cases) and run the pipeline concurrently, returning a consolidated coverage report suitable for regulatory submission packages.