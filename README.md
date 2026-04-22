# AutoQA — AI-Powered RTM Reviewer for Medical Device Software

## Background

AutoQA is a software quality tool designed to assist QA engineers and regulatory teams in reviewing Requirements Traceability Matrix (RTM) artifacts for medical device software. Medical device software developed under FDA guidance and the IEC 62304 lifecycle standard must demonstrate that every software requirement is adequately verified by a corresponding test case. In practice, this is a labor-intensive review process prone to coverage gaps, inconsistent rationale, and missed edge cases. AutoQA automates the analytical layer of that review by accepting a software requirement alongside its associated test suite and producing a **binary Yes/No coverage verdict** backed by a five-item mandatory rubric (M1 Functional, M2 Negative, M3 Boundary, M4 Spec Coverage, M5 Terminology), each finding citing the specific test cases or uncovered specs that support it, along with targeted clarification questions for the reviewer.

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
| `decomposed_requirement` | Requirement broken into atomic, dimension-agnostic specs (`spec_id`, `description`, `acceptance_criteria`, `rationale`). Dimension classification happens later, per covering test case, rather than at decomposition time. |
| `test_suite` | Structured summary of each test case — objective, protocol, acceptance criteria |
| `coverage_analysis` | Per-spec verdict: `covered_exists` (bool), `covered_by_test_cases` (list of `{test_case_id, dimensions[], rationale}` where each covering TC is labelled with the dimension(s) it exercises — any subset of `functional`, `negative`, `boundary` — and may cover multiple dimensions simultaneously), and a V&V `coverage_rationale` |
| `synthesized_assessment` | SoP-gating rubric: `overall_verdict` (`Yes`/`No`), `mandatory_findings` (exactly five items M1–M5 with Yes/No/N-A verdicts, cited TC IDs, and uncovered spec IDs), short `comments` clarifying gaps, and a list of `clarification_questions` that the reviewer can answer to confirm whether identified gaps are real or N/A in context |

The `overall_verdict` aggregates deterministically: it is `Yes` only when every mandatory finding is `Yes` or `N-A`; any single `No` flips it to `No`. `N-A` is permitted only on M2 (Negative) and M3 (Boundary) when the requirement has no validation surface or no threshold/limit surface respectively.

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

The integration test suite includes a session-scoped `jsonl_recorders` fixture that writes `inputs.jsonl` and `outputs.jsonl` to the active `logs/run-.../` folder, enabling offline analysis of model outputs across a batch of requirements. On session teardown the fixture also invokes `autoqa.viewer.write_viewer` to emit a self-contained HTML reviewer UI (`viewer.html`) whenever `outputs.jsonl` has records — no manual step required.

All run artifacts are written to a timestamped `logs/run-<datetime>/` directory:

| File | Contents |
|------|----------|
| `autoqa.log` | Structured application logs |
| `graph.png` | Mermaid diagram of the compiled LangGraph |
| `pipeline_state.json` | Full serialized state from a single pipeline run |
| `inputs.jsonl` | Input records fed to the parametrized test |
| `outputs.jsonl` | Serialized pipeline state for each parametrized run |
| `viewer.html` | Single-file HTML reviewer UI built from `outputs.jsonl` — auto-generated at session teardown |

---

## HTML Reviewer Viewer

Each batch run auto-emits `viewer.html` alongside `outputs.jsonl`. It is a single static file with inlined JSON and vanilla JavaScript — no server, CDN, or build step. Open it directly in a browser to page through the batch.

**Left panel (information):**
- `req_id` chip + full requirement text
- Clickable test-case list — opens a modal with the raw TC and its AI-parsed summary (objective, protocol, acceptance criteria)
- Coverage Assessment: overall Yes/No verdict badge (green/orange) plus a bulleted M1–M5 findings table with Yes/No/N-A chips, cited TC IDs, and uncovered spec IDs
- A "Decomposed specs & coverage analysis →" link opens a dialog showing every decomposed spec color-coded light green (covered) or light orange (uncovered), with per-spec covering TCs and dimension chips (`functional` / `negative` / `boundary`)
- Synthesizer `comments` and `clarification_questions` (rendered only when non-empty)

**Right panel (feedback capture):**
- 1–5 reviewer rating radios
- Free-text notes
- Prev / Save & Next navigation with a progress counter
- Ratings + notes persist to browser `localStorage` (keyed by `req_id`) and are exportable as a JSON blob via the header's **Export feedback JSON** button

### Regenerating the viewer manually

```bash
# module form
uv run python -m autoqa.viewer logs/run-<ts>/outputs.jsonl

# skill form (equivalent — the skill at .claude/skills/visualize-batch-outputs
# is a thin CLI wrapper over autoqa.viewer)
uv run python .claude/skills/visualize-batch-outputs/generate_viewer.py \
  logs/run-<ts>/outputs.jsonl
```

Use the `-o <path>` flag to redirect output. The viewer is also importable:

```python
from autoqa.viewer import write_viewer
write_viewer("logs/run-2026-04-22-09-00-00/outputs.jsonl")
```

### Package layout

```
autoqa/viewer/
├── __init__.py   # public API: build_viewer, write_viewer, HTML_TEMPLATE
├── __main__.py   # enables `python -m autoqa.viewer`
├── generator.py  # build_viewer / write_viewer / CLI main()
└── template.py   # HTML_TEMPLATE raw string (placeholders: {{TITLE}}, {{SOURCE}}, {{RUN_KEY}}, {{DATA}})
```

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
      "spec_id": "SRS-042-01",
      "covered_exists": true,
      "covered_by_test_cases": [
        {
          "test_case_id": "TC-101",
          "dimensions": ["functional"],
          "rationale": "TC-101 verifies the alarm fires above the configured threshold within the required 5-second window."
        },
        {
          "test_case_id": "TC-102",
          "dimensions": ["negative"],
          "rationale": "TC-102 verifies no alarm fires when the reading is below threshold."
        }
      ],
      "coverage_rationale": "TC-101 covers the positive case above threshold; TC-102 covers the below-threshold negative case. No test exercises the exact threshold value (180 mg/dL), leaving the boundary dimension uncovered for this spec."
    }
  ],
  "decomposed_requirement": {},
  "test_suite": {},
  "synthesized_assessment": {
    "requirement": {"req_id": "SRS-042", "text": "..."},
    "overall_verdict": "No",
    "mandatory_findings": [
      {"code": "M1", "dimension": "Functional", "verdict": "Yes", "rationale": "TC-101 verifies alarm activation above threshold.", "cited_test_case_ids": ["TC-101"], "uncovered_spec_ids": []},
      {"code": "M2", "dimension": "Negative", "verdict": "Yes", "rationale": "TC-102 verifies no alarm below threshold.", "cited_test_case_ids": ["TC-102"], "uncovered_spec_ids": []},
      {"code": "M3", "dimension": "Boundary", "verdict": "No", "rationale": "No test exercises the exact 180 mg/dL threshold or the 5-second timing boundary.", "cited_test_case_ids": [], "uncovered_spec_ids": []},
      {"code": "M4", "dimension": "Spec Coverage", "verdict": "Yes", "rationale": "all specs covered", "cited_test_case_ids": [], "uncovered_spec_ids": []},
      {"code": "M5", "dimension": "Terminology", "verdict": "Yes", "rationale": "aligned", "cited_test_case_ids": [], "uncovered_spec_ids": []}
    ],
    "comments": "Boundary coverage is absent at the exact 180 mg/dL threshold and at the upper edge of the 5-second latency window.",
    "clarification_questions": [
      "Should a boundary test at exactly 180 mg/dL be added, or is boundary behavior covered by a separate latency-specific requirement?"
    ]
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
        dims = sorted({d for ctc in spec["covered_by_test_cases"] for d in ctc["dimensions"]})
        tcs = [ctc["test_case_id"] for ctc in spec["covered_by_test_cases"]]
        print(f"[{spec['spec_id']}] covered={spec['covered_exists']}  dimensions={dims}")
        print(f"  Covered by: {tcs}")
        print(f"  Rationale:  {spec['coverage_rationale']}\n")

    assessment = result.get("synthesized_assessment") or {}
    print(f"Overall verdict: {assessment.get('overall_verdict')}")
    for finding in assessment.get("mandatory_findings", []):
        print(f"  [{finding['code']} {finding['dimension']}] {finding['verdict']} — {finding['rationale']}")
    if assessment.get("comments"):
        print(f"\nComments: {assessment['comments']}")
    for q in assessment.get("clarification_questions", []):
        print(f"  ? {q}")

asyncio.run(main())
```

---

## Current Work

AutoQA is under active development. The following capabilities are on the near-term roadmap:

**Individual test case reviews** — In addition to per-specification coverage scoring, a planned node will provide a deep-dive review of each individual test case: assessing completeness, checking for ambiguous pass/fail criteria, and flagging test cases that do not satisfy IEC 62304 traceability requirements.

**Additional medical device document types** — The review pipeline will be extended beyond RTM artifacts to support other regulatory and quality documents common in medical device software development, including Software Requirements Specifications (SRS), risk management files per ISO 14971, and records of Software of Unknown Provenance (SOUP).

**Persistent thread state** — The current implementation uses an in-memory checkpointer, meaning thread history is lost on server restart. A database-backed checkpointer (SQLite or PostgreSQL) is planned to support long-running review sessions and audit trail preservation.

**Batch review endpoint** — A `POST /api/v1/batch-review` endpoint is planned to accept a full RTM table (multiple requirements and their associated test cases) and run the pipeline concurrently, returning a consolidated coverage report suitable for regulatory submission packages.