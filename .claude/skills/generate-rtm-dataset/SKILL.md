---
name: generate-rtm-dataset
description: |
  Generate a synthetic Requirements Traceability Matrix (RTM) dataset for evaluating the
  autoqa test_suite_reviewer LangGraph as a binary classifier. Produces three files —
  inputs.jsonl, outputs.jsonl, and a description.md metadata file — where each input is a
  Requirement + traced TestCases and each output is the full pipeline state (decomposed
  requirement, test suite, coverage analysis, synthesized assessment with M1-M5 rubric).
  Records are explicitly labelled as "known good" (overall_verdict=Yes, no critical gaps)
  or "known bad" (overall_verdict=No, clear major gap). Default domain is medical-device
  software (SiMD / SaMD / IEC 82304); other domains can be requested. Includes
  power-analysis guidance on how many samples per class are needed before downstream ML
  metrics (accuracy, F1, per-rubric-cell coverage) become statistically meaningful. Use
  when the user asks to synthesize a labelled dataset, build training/eval data for the
  RTM reviewer, mock pipeline inputs at scale, or evaluate the pipeline as a classifier.
---

# generate-rtm-dataset

Generate a labelled, schema-conformant RTM dataset whose inputs match the
`test_suite_reviewer` graph's expected entry state and whose outputs match its
`RTMReviewState` final state. The dataset is binary-labelled (known good / known bad)
so it can drive ML evaluation of the LangGraph as a classifier.

This skill is a **content generator**. It writes three files to disk; it does not
invoke the LangGraph pipeline. To compare these synthetic outputs to actual pipeline
runs, point the integration tests in `tests/integration/test_pipeline.py` at the
generated `inputs.jsonl` and compare the produced `outputs.jsonl` against the
synthesized one.

## Persona

Adopt the voice of a **Principal Requirements Engineer & Test Architect** with 15+
years across aerospace, medical devices, automotive, financial services, and
enterprise software. Apply working knowledge of:

- IEEE 29148 (requirements engineering)
- IEC 62304 / IEC 82304 / ISO 14971 (medical device software, health software, risk)
- ISO 26262 (automotive), DO-178C (aerospace) — for non-default domains
- Black-box / white-box / gray-box testing strategies
- Boundary-value analysis, equivalence partitioning, state-transition testing
- V-model and TDD verification flows

## When to invoke

- "Generate a labelled RTM dataset / gold dataset / training set for the reviewer"
- "Create N known-good and M known-bad examples for evaluating the pipeline as a classifier"
- "Synthesize fixtures matching gold_dataset.jsonl format, but at scale"
- "Mock pipeline outputs for ML evaluation / power analysis / metric calibration"
- User mentions ROC, F1, accuracy, calibration, or sample-size estimation in the
  context of test_suite_reviewer
- User references `tests/fixtures/gold_dataset.jsonl` or `hc_pipeline_inputs.jsonl`
  and asks for a larger / labelled / per-class version

If the user asks for a *test-case-level* dataset (single test case + multi-spec
review) instead of a *test-suite-level* dataset, redirect to
`tests/fixtures/gold_dataset-tc.jsonl` and the `test_case_reviewer` schema. This
skill is RTM (test-suite-reviewer) specific.

## Inputs to gather before generating

If the user has not specified, ask once with `AskUserQuestion`:

1. **Domain** — default `medical-device-software (SiMD / SaMD / IEC 82304)`. Other
   accepted values: `aerospace (DO-178C)`, `automotive (ISO 26262)`, `financial
   services`, `enterprise SaaS`. Choose ONE realistic product within the domain
   (e.g. infusion pump SiMD, glucose-monitor SaMD, EHR clinical-decision-support).
2. **Total sample count** — see "Sample-size guidance" below for recommended
   defaults.
3. **Class balance** — default 50/50 known-good / known-bad. The user can override
   for skewed evaluation.
4. **Output directory** — default `tests/fixtures/generated/` (creates it if
   missing). Files: `inputs.jsonl`, `outputs.jsonl`, `description.md`.

## Schemas (single source of truth — DO NOT duplicate)

The skill MUST conform to the live Pydantic models. Read them before generating
to make sure field names / types / literals are exact:

- **Inputs (one record per line of `inputs.jsonl`)** — same shape as
  `tests/fixtures/gold_dataset.jsonl`:
  ```json
  {
    "requirement": {"req_id": "string", "text": "string"},
    "test_cases": [{"test_id", "description", "setup", "steps", "expectedResults"}, ...],
    "rationale": "string (why the suite satisfies the requirement)",
    "expected_gap": "string (the deliberate gap, or 'none' if known-good)",
    "description": "string (overall test-suite description)"
  }
  ```
- **Outputs (one record per line of `outputs.jsonl`)** — full `RTMReviewState`
  serialized. Source of truth: `autoqa/components/test_suite_reviewer/core.py`.
  Critical sub-models:
  - `Requirement`, `TestCase`, `DecomposedSpec`, `DecomposedRequirement`
  - `TestSuite` (`requirement`, `test_cases`, `summary[SummarizedTestCase]`)
  - `EvaluatedSpec` (`spec_id`, `covered_exists`, `covered_by_test_cases[CoveringTestCase]`)
  - `CoveringTestCase` (`test_case_id`, `dimensions: List[Literal["functional","negative","boundary"]]`, `rationale`)
  - `MandatoryFinding` (`code: Literal["M1","M2","M3","M4","M5"]`, `dimension`, `verdict: Literal["Yes","No","N-A"]`, `partial: bool`, `rationale`, `cited_test_case_ids`, `uncovered_spec_ids`)
  - `SynthesizedAssessment` (`requirement`, `overall_verdict`, `mandatory_findings` (exactly 5, M1..M5), `comments`, `clarification_questions`)
- **Rubric semantics** — read `autoqa/prompts/synthesizer-v6.jinja2` for the M1-M5
  definitions. Each row in the synthesized output must follow:
  - M1 Functional (never N-A) · M2 Negative (N-A allowed) · M3 Boundary (N-A allowed) · M4 Spec Coverage (never N-A) · M5 Terminology (never N-A)
  - `overall_verdict = "Yes"` iff every finding's verdict is in `{Yes, N-A}`.
  - `partial=true` requires `verdict="Yes"` AND incomplete coverage; never with No or N-A.

## Class definitions

### Known good (label = 1, overall_verdict = "Yes")
- Test suite verifies every decomposed spec the requirement carries.
- M1 functional Yes, with cited TC IDs.
- M2 negative either Yes (with cited TC IDs) or N-A (when the requirement has no
  validation surface — justify in rationale).
- M3 boundary either Yes (cited TC IDs) or N-A (when no threshold/limit).
- M4 spec coverage Yes (`uncovered_spec_ids = []`).
- M5 terminology Yes (rationale = "aligned").
- `clarification_questions` may be present for context but never expose a critical
  gap.
- `expected_gap` in input = `"none"`.

### Known bad (label = 0, overall_verdict = "No")
- At least one mandatory finding has `verdict = "No"` with a clear, plausibly-real
  defect — not a contrived edge case.
- The `expected_gap` field in input identifies which dimension is broken
  (`functional` / `negative` / `boundary` / `coverage` / `terminology`).
- The `rationale` of the failing finding must explain the gap concretely (cite
  specific TC IDs that are missing or specific spec_ids in `uncovered_spec_ids`).
- Do NOT make every record fail the same dimension — distribute failures across
  M1-M5 so per-rubric metrics have signal.

### Distribution across rubric cells
For statistical power on per-rubric metrics, target roughly equal failure
representation across M1-M5 within the known-bad class. With 50 known-bads this
means ~10 failures per dimension. Use the requirement type to make this natural:

- M1 failures: requirement has a clear functional behavior with no positive-path TC
- M2 failures: requirement has validation/error surfaces with no negative-path TC
- M3 failures: requirement names a threshold/limit/role-transition with no boundary TC
- M4 failures: requirement decomposes to multiple specs and one is uncovered
- M5 failures: TC vocabulary drifts from requirement vocabulary (e.g., requirement
  says "restricted access" but TC verifies "standard allocation")

## Sample-size guidance (statistical power)

Provide the user a recommendation grounded in three estimation regimes:

**Regime 1 — Single binary metric (e.g., overall accuracy)**
For a 95% confidence interval with margin of error ε on a Bernoulli success rate,
under a worst-case 50% prior:

```
n ≈ (1.96² × 0.25) / ε²  ≈ 0.96 / ε²   (per class)
```

| Margin ε | Per-class samples | Total (50/50 split) |
|---|---|---|
| ±10% | 96 | ≈ 200 |
| ±7%  | 196 | ≈ 400 |
| ±5%  | 384 | ≈ 800 |
| ±3%  | 1067 | ≈ 2200 |

**Regime 2 — Per-rubric-cell metric (M1-M5 × {Yes, No, N-A})**
With 5 rubric codes and realistic verdict distributions, you typically want ≥30
positive examples in each (rubric × verdict) cell. With M2/M3 also taking N-A,
that's up to 13 active cells. **A practical floor of ~30 known-bads per failing
rubric (≈150 known-bads total) plus 50-100 known-goods** gives enough headroom for
F1/recall per rubric without paying for ±5% precision on overall accuracy.

**Regime 3 — McNemar / paired comparison between two prompt versions**
For detecting a 5-percentage-point shift in agreement between two pipeline runs
with 80% power and α=0.05, ~150-200 paired examples is sufficient (under standard
McNemar assumptions).

**Default recommendation**: 100 known-good + 100 known-bad = 200 total. This gives
±7% CI on overall accuracy AND enough rubric-cell coverage to read per-dimension
metrics. Below 50/class, treat results as exploratory only.

State the recommendation to the user, then ask which sample size they want before
generating. Do not silently default to 200 if the user asked for 10.

## Generation procedure

1. **Confirm domain + product**. State the chosen product concretely (e.g.,
   "FluxPump 4000 — a Class II PCA infusion pump SiMD, IEC 62304 Class B"). All
   requirements and test cases anchor to this product.
2. **Generate requirements first**. For each record: write a 1-3 sentence
   requirement using SHALL / SHOULD / MAY appropriately. Include enough specificity
   that decomposing into 3-6 specs is natural. Use sequential req_ids
   (`REQ-PUMP-001`, `REQ-PUMP-002`, …).
3. **Decompose** each requirement into 3-6 atomic specs in
   `decomposed_requirement.decomposed_specifications`. spec_ids should be derived
   (`REQ-PUMP-001-01`, `REQ-PUMP-001-02`, …).
4. **Author traced test cases**. Use realistic test_ids (`TC-PUMP-001-A`,
   `TC-PUMP-001-B`, …). For known-goods, the test set must collectively verify
   every spec across functional + negative + boundary dimensions. For known-bads,
   the test set has the deliberate gap matching `expected_gap`.
5. **Build `test_suite.summary`** — one `SummarizedTestCase` per test case, with
   `protocol` and `acceptance_criteria` as lists of strings, `is_generated=false`
   (these are user-authored, not synthesizer-generated).
6. **Build `coverage_analysis`** — one `EvaluatedSpec` per spec. For each
   `covered_by_test_cases` entry, label dimensions accurately
   (`functional`/`negative`/`boundary`) — a single TC may carry multiple
   dimensions. `covered_exists=true` iff ≥1 non-AI-generated TC covers any
   dimension of the spec.
7. **Build `synthesized_assessment`** — exactly 5 mandatory findings, M1..M5 in
   order. Apply the rubric deterministically:
   - Compute each verdict from `coverage_analysis` (don't invent; mirror what the
     pipeline would emit).
   - Set `overall_verdict = "Yes"` iff every verdict is in `{Yes, N-A}`.
   - For known-goods: every verdict in `{Yes, N-A}`, partial usually false.
   - For known-bads: at least one verdict = "No" matching `expected_gap`.
8. **Validate** every output record against `SynthesizedAssessment.model_validate(...)`
   and `RTMReviewState` shape before writing.
9. **Write three files**:
   - `inputs.jsonl` — one input record per line.
   - `outputs.jsonl` — one output record per line, in the same order.
   - `description.md` — the metadata file (see structure below).

## description.md structure

```markdown
# Synthetic RTM Dataset — <Product Name>

## Domain & product
- Domain: <e.g., Medical Device Software (SaMD, IEC 82304)>
- Product: <e.g., FluxPump 4000 PCA infusion pump (Class II SiMD, IEC 62304 Class B)>
- Compliance frame: <e.g., IEC 62304, ISO 14971, FDA 21 CFR 820.30>

## Class distribution
- Known good (label=1, overall_verdict=Yes): N records
- Known bad  (label=0, overall_verdict=No):  M records
- Total: N+M

## Failure-mode distribution (known bads)
- M1 Functional No: x records
- M2 Negative No:   y records
- M3 Boundary No:   z records
- M4 Spec Coverage No: w records
- M5 Terminology No:   v records
(Sum = M)

## Statistical posture
- Margin of error on overall accuracy at 95% CI: ±X% (with current N+M)
- Per-rubric-cell minimum count: ≥30 / not yet
- Recommendation if scaling up: <next milestone>

## Schema references
- Input shape: tests/fixtures/gold_dataset.jsonl (one record per line)
- Output shape: autoqa/components/test_suite_reviewer/core.py::RTMReviewState
- Rubric: autoqa/prompts/synthesizer-v6.jinja2 (M1-M5)

## Assumptions and choices
- <Any product-specific simplifications>
- <Any rubric edge-case rulings made during generation>
- <Anything an evaluator should know before running ML metrics>
```

## Verification checklist (run before claiming done)

- ✓ All `req_id` values are unique and follow a consistent prefix.
- ✓ All `test_id` values are unique and follow a consistent pattern.
- ✓ Every requirement has ≥1 traced test case.
- ✓ Requirements use SHALL / SHOULD / MAY appropriately (no "the system will" /
  "should probably" weasel words).
- ✓ Technical specifications are realistic for the chosen product.
- ✓ Each output record validates against `SynthesizedAssessment` (load with
  `from autoqa.components.test_suite_reviewer.core import SynthesizedAssessment;
  SynthesizedAssessment.model_validate(record["synthesized_assessment"])`).
- ✓ Every output's `mandatory_findings` has exactly 5 items in M1..M5 order.
- ✓ Every `partial=true` finding has `verdict="Yes"`. No `partial=true` with No or N-A.
- ✓ `overall_verdict="Yes"` iff every finding verdict is in `{Yes, N-A}` (deterministic
  check — fail loudly if any record violates this).
- ✓ For known-bads: the failing dimension matches `expected_gap`.
- ✓ Across all known-bads, M1-M5 failure counts are balanced (no single dimension
  dominates ≥40% unless the user asked for that distribution).
- ✓ Inputs.jsonl line N corresponds to outputs.jsonl line N (same `req_id`).
- ✓ description.md numbers match the file row counts.

## Out of scope

- Running the pipeline against the generated inputs (use
  `tests/integration/test_pipeline.py::test_pipeline_parametrized` for that).
- Computing actual ML metrics (accuracy, F1, calibration) — this skill produces
  the dataset; metric computation is downstream.
- Cross-domain mixed datasets — pick one domain per generation run; if multi-domain
  is needed, run the skill twice and concatenate.
- Hazard-traceable inputs — for hazard-driven datasets use the
  `hazard_risk_reviewer` schema instead (`autoqa/components/hazard_risk_reviewer/core.py`).
