# AutoQA — AI-Powered DHF Reviewer for Medical Device Software

## Background

AutoQA is a software quality tool designed to assist QA engineers and regulatory teams in reviewing Design History File artifacts for medical device software developed under FDA guidance and the IEC 62304 / ISO 14971 lifecycle standards. These reviews must demonstrate that every software requirement is adequately verified by a corresponding test case, that each test case is itself well-formed, and that hazards in the risk register are mitigated by traceable controls. In practice, they are labor-intensive processes prone to coverage gaps, inconsistent rationale, and missed edge cases.

AutoQA exposes three complementary reviewers, each implemented as an independent LangGraph pipeline that emits a structured, SoP-gating rubric:

| Reviewer | What it scores | Output rubric |
|----------|----------------|---------------|
| **Test Suite Reviewer (RTM)** — `/api/v1/review` | One requirement against its associated test suite | M1-M5 mandatory findings (Functional / Negative / Boundary / Spec Coverage / Terminology) → binary Yes/No coverage verdict |
| **Hazard Coverage Reviewer** — `/api/v1/hazard-review` | One hazard register entry against its traced requirements + test cases + design docs | H1-H5 mandatory findings (Hazard Statement Completeness / Pre-Mitigation Risk / Risk Control Adequacy / Verification Depth / Residual Risk Closure) → Adequate / Partial / Inadequate verdict |
| **Single Test Case Reviewer** — library only (`autoqa.components.test_case_reviewer`) | One test case against its requirements and a checklist of review objectives | Per-objective Yes/No verdicts (with a `partial` flag for material gaps) → binary Yes/No overall verdict |

All three reviewers cite the artifact IDs that support each finding, return short comments clarifying any gaps, and emit closed-ended clarification questions so reviewers can quickly confirm whether flagged gaps are real or N/A in context.

---

## Pipeline Architecture

Every reviewer is a LangGraph `StateGraph` that fans out via the `Send` API for maximum parallelism, then fans back in via `operator.add` reducers before a synthesizer node aggregates findings against the rubric. Each run also writes a Mermaid graph PNG (`graph.png`, `hazard_graph.png`, or `tc_graph.png`) into the run's log folder alongside `autoqa.log`.

### Test Suite Reviewer (RTM coverage)

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

### Hazard Coverage Reviewer

The hazard pipeline reuses the test suite reviewer as an atomic subgraph: each requirement traced from a `HazardRecord` is reviewed in parallel by invoking the full RTM graph for that requirement, then a hazard-level synthesizer rolls all M1-M5 findings up into the H1-H5 rubric.

```
START
  ↓ dispatch_requirement_reviews → Send × N
┌──────────────────────────────────────┐
│ REQUIREMENT_REVIEWER × N (parallel)  │  ← each invokes the entire RTM subgraph
└──────────────────────────────────────┘
  ↓ (fan-in: operator.add accumulates requirement_reviews)
┌──────────────────────────────────────┐
│ HAZARD_SYNTHESIZER  (H1-H5 rubric)   │
└──────────────────────────────────────┘
  ↓
END
```

### Single Test Case Reviewer

A test case plus its traced requirements and a review-objectives checklist enter at `START`. The decomposer splits each requirement into atomic specs; a no-op `coverage_router` then fans out **three independent waves of Sends** — one per review axis (coverage / logical / prereqs) — to per-spec evaluators that run in parallel. The aggregator synthesizes the three accumulated `SpecAnalysis` lists into a single `TestCaseAssessment` with the review-objectives checklist populated.

```
START
  ↓
┌──────────────────────────────────────┐
│ DECOMPOSER (sequential per req)      │
└──────────────────────────────────────┘
  ↓
┌──────────────────────────────────────┐
│ COVERAGE_ROUTER (sync point)         │
└──────────────────────────────────────┘
  ↓ 3× Send × N (parallel waves per axis)
┌─────────────┬─────────────┬──────────┐
│ COVERAGE    │ LOGICAL     │ PREREQS  │
│ EVAL × N    │ EVAL × N    │ EVAL × N │
└─────────────┴─────────────┴──────────┘
  ↓ (operator.add reducers fan in per axis)
┌──────────────────────────────────────┐
│ AGGREGATOR  (MoA-like synthesis)     │
└──────────────────────────────────────┘
  ↓
END
```

### Test Suite Reviewer output fields

| Field | Description |
|-------|-------------|
| `decomposed_requirement` | Requirement broken into atomic, dimension-agnostic specs (`spec_id`, `description`, `acceptance_criteria`, `rationale`). Dimension classification happens later, per covering test case, rather than at decomposition time. |
| `test_suite` | Structured summary of each test case — objective, protocol, acceptance criteria |
| `coverage_analysis` | Per-spec verdict: `covered_exists` (bool), `covered_by_test_cases` (list of `{test_case_id, dimensions[], rationale}` where each covering TC is labelled with the dimension(s) it exercises — any subset of `functional`, `negative`, `boundary` — and may cover multiple dimensions simultaneously), and a V&V `coverage_rationale` |
| `synthesized_assessment` | SoP-gating rubric: `overall_verdict` (`Yes`/`No`), `mandatory_findings` (exactly five items M1–M5 with Yes/No/N-A verdicts, cited TC IDs, and uncovered spec IDs), short `comments` clarifying gaps, and a list of `clarification_questions` that the reviewer can answer to confirm whether identified gaps are real or N/A in context |

The `overall_verdict` aggregates deterministically: it is `Yes` only when every mandatory finding is `Yes` or `N-A`; any single `No` flips it to `No`. `N-A` is permitted only on M2 (Negative) and M3 (Boundary) when the requirement has no validation surface or no threshold/limit surface respectively.

### Hazard Coverage Reviewer output fields

| Field | Description |
|-------|-------------|
| `requirement_reviews` | One `RequirementReview` per requirement traced from the `HazardRecord`, each carrying the M1-M5 `synthesized_assessment` plus the RTM byproducts (`decomposed_requirement`, `test_suite`, `coverage_analysis`) — the full evidence chain that drove the hazard verdict |
| `hazard_assessment.mandatory_findings` | Exactly five items in order — H1 Hazard Statement Completeness, H2 Pre-Mitigation Risk, H3 Risk Control Adequacy, H4 Verification Depth, H5 Residual Risk Closure — each with an `Adequate` / `Partial` / `Inadequate` (or `N-A` on H4 only) verdict, cited `req_id`s and `test_id`s, and `unblocked_items` (sequence-of-events steps without controlling requirements on H3, controls without verifying tests on H4) |
| `hazard_assessment.overall_verdict` | `Adequate` iff every finding is `Adequate` or `N-A`; `Inadequate` if any is `Inadequate`; `Partial` otherwise |
| `hazard_assessment.comments` / `clarification_questions` | Same shape as the RTM reviewer — short prose plus closed-ended questions to drive reviewer follow-up |

### Single Test Case Reviewer output fields

| Field | Description |
|-------|-------------|
| `decomposed_requirements` | Each traced requirement broken into atomic specs (same `DecomposedSpec` shape as the RTM reviewer) |
| `coverage_analysis` / `logical_structure_analysis` / `prereqs_analysis` | Three parallel `SpecAnalysis` lists — one per axis — each entry: `{spec_id, exists (bool), assessment}` |
| `aggregated_assessment.evaluated_checklist` | The input `review_objectives` checklist populated with `verdict` (`Yes`/`No`), a `partial` flag (drives Yellow rendering when verdict is `Yes` but coverage is materially incomplete), and an `assessment` rationale per item |
| `aggregated_assessment.overall_verdict` | `Yes` iff every objective is `Yes`; partial-Yes still counts as `Yes` |
| `aggregated_assessment.comments` / `clarification_questions` | Same shape as the other reviewers |

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

# Hazard coverage reviewer pipeline (uses tests/fixtures/sample_hazard.json)
uv run pytest tests/integration/test_hazard_pipeline.py -m integration -s
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

The interactive API documentation is available at `http://localhost:8000/docs` once the server is running. At startup the lifespan handler builds a single shared `RTMReviewerRunnable` and reuses it inside the hazard pipeline's `RequirementReviewerNode`, so the RTM graph compiles and renders `graph.png` only once per process even though both endpoints exercise it.

### Endpoint Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/review` | Submit a requirement + test suite for RTM coverage analysis (M1-M5 rubric) |
| `POST` | `/api/v1/hazard-review` | Submit a `HazardRecord` (hazard line item + traced requirements / test cases / design docs) for hazard mitigation coverage analysis (H1-H5 rubric) |

---

### Test Suite Reviewer — `/api/v1/review`

#### Quickstart: curl

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

#### Quickstart: Python

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

### Hazard Coverage Reviewer — `/api/v1/hazard-review`

The endpoint accepts a single `HazardRecord` carrying the hazard register fields (per ISO 14971 / IEC 62304) plus the requirements, test cases, and design docs traced to that hazard. The pipeline fans out one parallel RTM review per traced requirement, then applies the H1-H5 rubric across the full hazard envelope. A complete sample input is at `tests/fixtures/sample_hazard.json`.

#### Quickstart: curl

```bash
curl -X POST http://localhost:8000/api/v1/hazard-review \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/sample_hazard_request.json
```

where `sample_hazard_request.json` wraps the fixture with a `thread_id`:

```json
{
  "thread_id": "hazard-session-001",
  "hazard": {
    "hazard_id": "HAZ-PUMP-001",
    "hazardous_situation_id": "HS-PUMP-001",
    "hazard": "Over-infusion of medication due to software loop hang",
    "hazardous_situation": "Patient receives medication at the maximum pump rate continuously...",
    "function": "Continuous infusion rate control loop",
    "ots_software": "FreeRTOS 10.4.3",
    "hazardous_sequence_of_events": "1. Periodic timer ISR fails to fire... 2. Rate-control loop continues...",
    "software_related_causes": "Scheduler stall under heavy task load; missing independent watchdog...",
    "harm_severity_rationale": "External risk controls reduce but do not eliminate...",
    "harm": "Severe over-infusion with potential for life-threatening overdose",
    "severity": "Catastrophic",
    "exploitability_pre_mitigation": "Not applicable",
    "probability_of_harm_pre_mitigation": "Probable",
    "initial_risk_rating": "Unacceptable",
    "risk_control_measures": "REQ-PUMP-101 mandates an independent hardware watchdog...",
    "demonstration_of_effectiveness": "Verified by TC-PUMP-201, TC-PUMP-202, TC-PUMP-203.",
    "severity_of_harm_post_mitigation": "Catastrophic",
    "exploitability_post_mitigation": "Not applicable",
    "probability_of_harm_post_mitigation": "Remote",
    "final_risk_rating": "Acceptable",
    "new_hs_reference": "",
    "sw_fmea_trace": "FMEA-PUMP-RC-001",
    "sra_link": "SRA-PUMP-2025-12",
    "urra_item": "URRA-PUMP-RC-001",
    "residual_risk_acceptability": "Per GQP-10-02 Risk Management Report, residual risk is acceptable...",
    "requirements": [
      {"req_id": "REQ-PUMP-101", "text": "The rate-control loop shall be monitored by an independent hardware watchdog..."},
      {"req_id": "REQ-PUMP-102", "text": "The UI thread shall render an Alarm Mode banner..."}
    ],
    "test_cases": [
      {"test_id": "TC-PUMP-201", "description": "Functional verification of watchdog heartbeat...", "setup": "...", "steps": "...", "expectedResults": "..."},
      {"test_id": "TC-PUMP-202", "description": "Fault injection — simulate scheduler stall...", "setup": "...", "steps": "...", "expectedResults": "..."},
      {"test_id": "TC-PUMP-203", "description": "Boundary — heartbeat latency at 200 ms threshold...", "setup": "...", "steps": "...", "expectedResults": "..."}
    ],
    "design_docs": [
      {"doc_id": "DD-PUMP-RC-001", "name": "Rate Control Loop and Watchdog Architecture", "description": "..."}
    ]
  }
}
```

#### Quickstart: Python

```python
import asyncio
import json
from pathlib import Path

import httpx

hazard = json.loads(Path("tests/fixtures/sample_hazard.json").read_text())
payload = {"thread_id": "hazard-session-001", "hazard": hazard}

async def main():
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            "http://localhost:8000/api/v1/hazard-review",
            json=payload,
        )
        result = response.json()

    assessment = result.get("hazard_assessment") or {}
    print(f"Hazard {assessment.get('hazard_id')}: {assessment.get('overall_verdict')}")
    for f in assessment.get("mandatory_findings", []):
        print(f"  [{f['code']} {f['dimension']}] {f['verdict']} — {f['rationale']}")
        if f.get("cited_req_ids"):
            print(f"      cited reqs:  {f['cited_req_ids']}")
        if f.get("cited_test_case_ids"):
            print(f"      cited tests: {f['cited_test_case_ids']}")
        if f.get("unblocked_items"):
            print(f"      unblocked:   {f['unblocked_items']}")

    # Drill into each per-requirement RTM assessment that fed the H1-H5 roll-up
    for review in result.get("requirement_reviews", []):
        sa = review.get("synthesized_assessment") or {}
        print(f"\n  {review['requirement']['req_id']}: {sa.get('overall_verdict')}")
        for mf in sa.get("mandatory_findings", []):
            print(f"    [{mf['code']}] {mf['verdict']} — {mf['rationale']}")

asyncio.run(main())
```

H4 (Verification Depth) is the only finding that may be `N-A` — it applies when `software_related_causes` indicates no software cause, in which case test-case verification is not required for that hazard. H1, H2, H3, and H5 must always resolve to `Adequate`, `Partial`, or `Inadequate`.

---

### Single Test Case Reviewer — library API

The single-test-case reviewer is currently library-only (no HTTP endpoint). Construct a `TCReviewerRunnable` directly and invoke its compiled graph. The default review-objectives checklist lives at `autoqa/components/test_case_reviewer/review_objectives.yaml`; load it with `load_default_review_objectives()` or substitute your own list of `ReviewObjective` rows.

```python
import asyncio

from autoqa.components.clients import RateLimitOpenAIClient
from autoqa.components.shared.core import Requirement, TestCase
from autoqa.components.test_case_reviewer.nodes import load_default_review_objectives
from autoqa.components.test_case_reviewer.pipeline import TCReviewerRunnable
from autoqa.core.config import settings


async def main():
    client = RateLimitOpenAIClient(api_key=settings.openai_api_key)
    runnable = TCReviewerRunnable(client=client, model=settings.model)

    test_case = TestCase(
        test_id="TC-101",
        description="Verify high-glucose alarm activation",
        setup="Device powered on, high threshold set to 180 mg/dL",
        steps="Simulate glucose reading of 200 mg/dL via test fixture",
        expectedResults="Audible alarm sounds and alert banner displayed within 5 seconds",
    )
    requirements = [
        Requirement(
            req_id="SRS-042",
            text="The system shall generate an audible and visual alarm within 5 seconds when the measured glucose concentration exceeds the user-configured high threshold.",
        )
    ]

    result = await runnable.graph.ainvoke({
        "test_case": test_case,
        "requirements": requirements,
        "review_objectives": load_default_review_objectives(),
    })

    assessment = result.get("aggregated_assessment")
    print(f"Overall verdict: {assessment.overall_verdict}")
    for item in assessment.evaluated_checklist:
        partial = " (partial)" if item.partial else ""
        print(f"  [{item.id}] {item.verdict}{partial} — {item.assessment}")
    if assessment.comments:
        print(f"\nComments: {assessment.comments}")
    for q in assessment.clarification_questions:
        print(f"  ? {q}")

asyncio.run(main())
```

The pipeline emits three independent `SpecAnalysis` lists on the final state — `coverage_analysis`, `logical_structure_analysis`, and `prereqs_analysis` — which the aggregator collapses into the populated `evaluated_checklist`. Inspect the per-axis lists directly when you need to see why the aggregator settled on a given verdict.

---

## Current Work

AutoQA is under active development. The following capabilities are on the near-term roadmap:

**Individual test case reviews** — In addition to per-specification coverage scoring, a planned node will provide a deep-dive review of each individual test case: assessing completeness, checking for ambiguous pass/fail criteria, and flagging test cases that do not satisfy IEC 62304 traceability requirements.

**Additional medical device document types** — The review pipeline will be extended beyond RTM artifacts to support other regulatory and quality documents common in medical device software development, including Software Requirements Specifications (SRS), risk management files per ISO 14971, and records of Software of Unknown Provenance (SOUP).

**Persistent thread state** — The current implementation uses an in-memory checkpointer, meaning thread history is lost on server restart. A database-backed checkpointer (SQLite or PostgreSQL) is planned to support long-running review sessions and audit trail preservation.

**Batch review endpoint** — A `POST /api/v1/batch-review` endpoint is planned to accept a full RTM table (multiple requirements and their associated test cases) and run the pipeline concurrently, returning a consolidated coverage report suitable for regulatory submission packages.