---
name: generate-tc-dataset
description: |
  Generate a synthetic dataset for evaluating the autoqa test_case_reviewer LangGraph
  as a binary classifier. Produces three files — inputs.jsonl, outputs.jsonl, and a
  description.md metadata file — where each input is a TestCase + a list of upstream
  requirements (one or more) and each output is the full TCReviewState (decomposed
  requirements, per-spec coverage_analysis, scalar OverallAnalysis for logical and
  prereqs, and an aggregated TestCaseAssessment with a 5-row evaluated_checklist:
  expected_result_support, expected_result_spec_align, test_case_achieves,
  test_case_logical_sequence, test_case_setup_clarity). Records are labelled "known
  good" (overall_verdict=Yes; sub-classified as full-green or yes-partial),
  "known bad" (overall_verdict=No, with a designated primary_failure objective).
  Default domain is medical-device software (SiMD / SaMD / IEC 82304); other domains
  can be requested. Includes power-analysis guidance on how many samples per class
  and per-objective cell are needed for confident ML evaluation. Use when the user
  asks to synthesize a labelled dataset for the test_case_reviewer, build training/
  eval data for the per-test-case checklist reviewer, mock TC pipeline inputs at
  scale, or evaluate the test_case_reviewer as a classifier. Sibling to
  generate-rtm-dataset (which targets the test_suite_reviewer graph instead).
---

# generate-tc-dataset

Generate a labelled, schema-conformant dataset whose inputs match the
`test_case_reviewer` graph's expected entry state and whose outputs match the
serialized `TCReviewState`. The dataset is binary-labelled (known good / known
bad) with a partial sub-class on known-goods, so it can drive ML evaluation of
the LangGraph as a classifier.

This skill is a **content generator**. It writes three files to disk; it does
not invoke the LangGraph pipeline. To compare these synthetic outputs to actual
pipeline runs, point `tests/integration/test_tc_pipeline.py::test_tc_pipeline_parametrized_fanout`
at the generated `inputs.jsonl` and compare its produced `outputs.jsonl`
against the synthesized one.

## Sibling skill

This is the test-case-reviewer counterpart of `generate-rtm-dataset`. The two
target different graphs:

| | `generate-rtm-dataset` (test_suite_reviewer) | `generate-tc-dataset` (this skill) |
|---|---|---|
| Input shape | one Requirement + List[TestCase] | one TestCase + List[Requirement] |
| Output rubric | M1-M5 mandatory findings (Yes/No/N-A) | 5 review objectives (Yes/No + partial flag) |
| Per-spec axis | coverage with `dimensions[functional/negative/boundary]` per TC | coverage with per-spec `exists` only |
| Other axes | (rolled up by synthesizer) | logical_structure_analysis + prereqs_analysis (test-level scalar OverallAnalysis) |
| Reference fixture | `tests/fixtures/gold_dataset.jsonl` | `tests/fixtures/gold_dataset-tc.jsonl` |
| Pydantic source-of-truth | `autoqa/components/test_suite_reviewer/core.py` | `autoqa/components/test_case_reviewer/core.py` |

If the user wants RTM (one-requirement-many-test-cases) data, redirect to
`generate-rtm-dataset`. This skill is TC (one-test-case-many-requirements) only.

## Persona

Adopt the voice of a **Principal Verification & Validation (V&V) Architect** for
safety-critical medical device software (IEC 62304 / IEC 82304 / ISO 14971 /
FDA 21 CFR Part 820.30). Apply working knowledge of:

- IEEE 29148 (requirements engineering)
- IEC 62304 / IEC 82304 / ISO 14971 (medical device software, health software, risk)
- ISO 26262 (automotive) / DO-178C (aerospace) — for non-default domains
- V&V test-case authoring: setup specificity, stimulus-response framing, terminal
  verification, traceability to requirement intent
- Black-box / white-box / gray-box testing strategies; boundary-value analysis;
  state-transition testing

## When to invoke

- "Generate a labelled test-case-reviewer dataset / training set / gold dataset"
- "Create N known-good and M known-bad test cases for evaluating the TC pipeline"
- "Synthesize fixtures matching gold_dataset-tc.jsonl format, but at scale"
- "Mock TC pipeline outputs for ML evaluation / power analysis / metric calibration"
- User mentions accuracy, F1, calibration, or sample-size estimation in the
  context of `test_case_reviewer` / `TCReviewerRunnable`
- User references `tests/fixtures/gold_dataset-tc.jsonl` and asks for a larger
  / labelled / per-class version
- User asks for examples per-objective failure mode (e.g. "10 examples that fail
  test_case_achieves")

## Inputs to gather before generating

If the user has not specified, ask once with `AskUserQuestion`:

1. **Domain** — default `medical-device software (SiMD / SaMD / IEC 82304)`. Other
   accepted values: `aerospace (DO-178C)`, `automotive (ISO 26262)`, `financial
   services`, `enterprise SaaS`. Choose ONE realistic product (e.g. infusion pump
   SiMD, glucose-monitor SaMD, EHR clinical-decision-support module).
2. **Total sample count** — see "Sample-size guidance" below for recommended
   defaults.
3. **Class balance** — default 50/50 known-good / known-bad. Within known-goods,
   default sub-balance is 60% full-green / 40% yes-partial.
4. **Failure-objective distribution within known-bads** — default uniform across
   the 5 objectives (20% each). Can be skewed per request.
5. **Multi-requirement frequency** — default 30% of records carry 2-3 upstream
   requirements; remaining 70% carry one. The skill should weight in favour of
   single-requirement records since that's the simpler base case.
6. **Output directory** — default `tests/fixtures/generated-tc/` (creates it if
   missing). Files: `inputs.jsonl`, `outputs.jsonl`, `description.md`.

## Schemas (single source of truth — DO NOT duplicate)

The skill MUST conform to the live Pydantic models. Read them before generating:

- **Inputs (one record per line of `inputs.jsonl`)** — same shape as
  `tests/fixtures/gold_dataset-tc.jsonl`:
  ```json
  {
    "test_case": {
      "test_id": "string",
      "description": "string",
      "setup": "string",
      "steps": "string (multi-line; 'Step: 1. ...\\nStep: 2. ...' format)",
      "expectedResults": "string (multi-line; 'ExpectedResult: 1. ...' format)"
    },
    "upstream_requirements": [
      {"req_id": "string", "text": "string"},
      ...
    ],
    "expected_overall_verdict": "Yes" | "No",
    "expected_partial_objectives": ["objective_id", ...],
    "primary_failure": "objective_id" | null,
    "description": "string (design-intent explainer)"
  }
  ```
- **Outputs (one record per line of `outputs.jsonl`)** — full `TCReviewState`
  serialized. Source of truth: `autoqa/components/test_case_reviewer/core.py`.
  Critical sub-models:
  - `Requirement`, `TestCase`, `DecomposedSpec`, `DecomposedRequirement`
  - `SpecAnalysis` (`spec_id`, `exists: bool`, `assessment: str`) — per-spec
  - `OverallAnalysis` (`exists: bool`, `assessment: str`) — test-case-level for
    logical_structure_analysis and prereqs_analysis
  - `ReviewObjective` (`id`, `description`)
  - `EvaluatedReviewObjective` (`id`, `description`, `verdict: Literal["Yes","No"]`,
    `partial: bool`, `assessment: str`)
  - `TestCaseAssessment` (`test_case`, `requirements`, `decomposed_requirements`,
    `evaluated_checklist[5]`, `overall_verdict`, `comments`, `clarification_questions`)
- **Review-objectives checklist** — must use the exact 5 objective ids from
  `autoqa/components/test_case_reviewer/review_objectives.yaml`:
  - `expected_result_support`
  - `expected_result_spec_align`
  - `test_case_achieves`
  - `test_case_logical_sequence`
  - `test_case_setup_clarity`
- **Aggregator rubric** — read `autoqa/prompts/single-test-aggregator-v4.jinja2`
  for the per-objective rules. Critical:
  - `expected_result_spec_align`: COUNT-BASED tier on `coverage_analysis`. All
    `exists=true` → Yes (no partial). ≥1 `exists=true` but not all → Yes (partial).
    Zero → No.
  - `expected_result_support`, `test_case_achieves`: requirement-level — multi-req
    tier (all-supported = Yes, ≥1-supported = Yes+partial, none = No).
  - `test_case_logical_sequence`, `test_case_setup_clarity`: test-case-level
    (independent of requirements). Yes/No on whether the property holds at the
    test level; partial=true when minor issue.
  - `overall_verdict`: deterministic AND across all 5 verdicts. Partial-Yes still
    counts as Yes.
  - `partial=true` requires `verdict="Yes"`; never with No.

## Class definitions

### Known good (label = 1, overall_verdict = "Yes")

Two sub-classes:

**Full-green (no partials)** — every `evaluated_checklist[i].verdict == "Yes"` AND
`partial == False`. Implies:
- coverage_analysis: every spec has `exists=true` (drives spec_align Yes-no-partial).
- expected results support every traced requirement with measurable evidence.
- test ends with explicit verification of every traced requirement's intent.
- logical_structure_analysis: clean precondition → stimulus → verification flow.
- prereqs_analysis: setup names version/role/data/external-dependency state.

**Yes-partial** — `overall_verdict == "Yes"` but at least one objective has
`partial == true` (verdict still Yes). Per the rubric:
- spec_align partial: ≥1 spec covered but not all (multi-spec requirement, partial coverage).
- support partial: ≥1 requirement supported but some expectedResults are vague.
- achieves partial: ≥1 requirement verified but final-step verification is light.
- logical_sequence partial: mostly logical with one minor ordering ambiguity.
- setup_clarity partial: most preconditions documented but one minor gap.

For each yes-partial record, encode the partial set in `expected_partial_objectives`
(list of objective ids). `primary_failure` stays `null`.

### Known bad (label = 0, overall_verdict = "No")

At least one objective has `verdict == "No"`. The deliberate failure mode is
encoded in `primary_failure` (objective id). Per-objective failure modes:

- **expected_result_support**: ExpectedResults are blank, vague ("Page loads correctly"),
  or lack measurable evidence for what the requirement asks. Cite specific
  expectedResult numbers in the synthesized assessment.
- **expected_result_spec_align**: NONE of the decomposed specs are covered by the
  test (count rule = 0 → No). Easiest mode: traced requirement is off-topic
  relative to what the test actually verifies.
- **test_case_achieves**: Test runs the stimulus but stops short of verifying
  the requirement's intent. Final step is a click without inspection of the
  resulting state.
- **test_case_logical_sequence**: Steps are scrambled — verification before
  stimulus, contradictory steps, no terminal verification. Cite the specific
  out-of-order step number(s) in the rationale.
- **test_case_setup_clarity**: Setup is trivial ("Module open."), missing
  version / role / data state / external-dependency state. The rationale should
  name the specific missing precondition.

Encode the failure mode in `primary_failure`. Note that some failure modes
**cascade** structurally — e.g. failing `test_case_setup_clarity` (prereqs
exists=false) does NOT directly affect spec_align (which counts coverage only),
but failing `expected_result_spec_align` may cascade into `expected_result_support`
and `test_case_achieves` because all three reason about whether the test
verifies the requirement. Mention cascades in the per-record `description` field
so consumers know which Nos are primary and which are downstream.

## Sample-size guidance (statistical power)

Provide the user a recommendation grounded in three estimation regimes:

**Regime 1 — Single binary metric (overall accuracy)**

For a 95% CI with margin of error ε on a Bernoulli success rate, under a worst-case 50% prior:

```
n_per_class ≈ (1.96² × 0.25) / ε²  ≈  0.96 / ε²
```

| Margin ε | Per-class samples | Total (50/50 split) |
|---|---|---|
| ±10% | 96 | ≈ 200 |
| ±7% | 196 | ≈ 400 |
| ±5% | 384 | ≈ 800 |
| ±3% | 1067 | ≈ 2200 |

**Regime 2 — Per-objective metric (5 objectives × {Yes, No})**

With 5 objectives and binary verdict (no N-A in this component), there are 10
verdict cells. For ≥30 examples in each (objective × verdict) cell as a working
floor for stable per-objective F1/recall: ~150 known-bads spread across the 5
failing objectives (30 each) plus 50-100 known-goods gives readable per-objective
metrics.

**Regime 3 — Partial-flag detection**

To evaluate the LLM's ability to set `partial=true` correctly, you need
known-yes-partial records where the *correct* answer is Yes-partial. Default 25-50
yes-partial records spread evenly across the 5 objectives gives 5-10 per partial
cell — enough to detect calibration issues but not for tight per-cell CIs.

**Default recommendation**: 100 known-good (60 full-green + 40 yes-partial) +
100 known-bad (20 each across 5 failure objectives) = 200 total. This gives ±10%
CI on overall accuracy AND enough per-objective coverage to read primary
metrics. Below 50/class, treat results as exploratory only.

State the recommendation explicitly to the user, then ask which sample size they
want before generating. Do not silently default to 200 if the user asked for 10.

## Generation procedure

1. **Confirm domain + product**. State the product concretely (e.g.,
   "FluxSense G7 — a Class II Continuous Glucose Monitor SaMD, IEC 62304 Class
   B"). All test cases anchor to this product.
2. **Pre-author requirement library**. Author 8-15 candidate requirements for
   the chosen product, each decomposable into 3-5 specs. Each requirement must
   have:
   - SHALL / SHOULD / MAY phrasing
   - Concrete numeric thresholds where relevant (so test cases can hit / probe
     them)
   - Identifiable acceptance criteria for each spec
3. **Generate test cases**. For each output record:
   - Pick 1-3 upstream_requirements from the library (default 70% single,
     20% double, 10% triple).
   - Compose a TestCase that — depending on label — either fully verifies every
     spec across functional/negative/boundary dimensions (full-green known-good),
     partially covers (yes-partial), or contains the deliberate failure mode
     (known-bad).
   - test_id format: `TC-<DOMAIN>-<seq>` (e.g. `TC-CGM-001`).
   - setup: name version, role, patient/data state, external-dependency state.
   - steps: `Step: 1. ...\nStep: 2. ...` multi-line.
   - expectedResults: `ExpectedResult: 1. ...\nExpectedResult: 2. ...` multi-line.
4. **Decompose** each upstream requirement into 3-5 specs in
   `decomposed_requirements`. spec_ids should follow `<req_id>-<NN>`
   (e.g. `REQ-CGM-001-01`, `REQ-CGM-001-02`).
5. **Build coverage_analysis** — one `SpecAnalysis` per spec across all
   decomposed requirements. For full-green: every `exists=true`. For yes-partial
   on spec_align: 1 ≤ exists=true count < total. For known-bad with
   primary_failure=expected_result_spec_align: every `exists=false`. For other
   primary_failures: every `exists=true` (the count rule is satisfied; the
   failure is on a different objective).
6. **Build logical_structure_analysis** (scalar `OverallAnalysis`) — `exists`
   reflects whether `test_case.steps` form a clean precondition → stimulus →
   verification flow. Assessment cites specific step numbers and what each
   does (no generic "steps are coherent" language).
7. **Build prereqs_analysis** (scalar `OverallAnalysis`) — `exists` reflects
   whether `test_case.setup` documents enough preconditions for reproducibility.
   Assessment names specific documented + missing preconditions (no generic
   "setup is sufficient" language).
8. **Build aggregated_assessment** — populate `evaluated_checklist` by applying
   the v4 aggregator rubric:
   - Echo `test_case`, `requirements`, `decomposed_requirements` verbatim.
   - For each of the 5 review objectives, emit an `EvaluatedReviewObjective`
     with id and description preserved verbatim, verdict + partial per the rule,
     and a 1-2 sentence assessment citing concrete evidence (step numbers,
     expectedResult numbers, req_ids, spec_ids — never generic).
   - `overall_verdict = "Yes"` iff every checklist verdict is `"Yes"`.
9. **Validate** every output record against `TestCaseAssessment.model_validate(...)`
   and verify the `partial` discipline (never with verdict=No).
10. **Write three files**:
    - `inputs.jsonl` — one input record per line.
    - `outputs.jsonl` — one output record per line, in the same order.
    - `description.md` — the metadata file (see structure below).

## description.md structure

```markdown
# Synthetic test_case_reviewer Dataset — <Product Name>

## Domain & product
- Domain: <e.g., Medical Device Software (SaMD, IEC 82304)>
- Product: <e.g., FluxSense G7 CGM (Class II SaMD, IEC 62304 Class B)>
- Compliance frame: <e.g., IEC 62304, ISO 14971, FDA 21 CFR 820.30>

## Class distribution
- Known good: N records
  - Full-green (no partials): X
  - Yes-partial (≥1 partial, overall=Yes): Y
- Known bad: M records
- Total: N+M

## Per-objective distribution

### Yes-partial (which objective carries the partial flag)
- expected_result_support partial: a
- expected_result_spec_align partial: b
- test_case_achieves partial: c
- test_case_logical_sequence partial: d
- test_case_setup_clarity partial: e

### Known-bad primary_failure (which objective drives the No)
- expected_result_support No: f
- expected_result_spec_align No: g
- test_case_achieves No: h
- test_case_logical_sequence No: i
- test_case_setup_clarity No: j

## Multi-requirement distribution
- Single upstream requirement: P records
- Two upstream requirements: Q records
- Three or more: R records

## Statistical posture
- Margin of error on overall accuracy at 95% CI: ±X%
- Per-objective per-verdict cell minimum count: ≥30 / not yet
- Recommendation if scaling up: <next milestone>

## Schema references
- Input shape: tests/fixtures/gold_dataset-tc.jsonl
- Output shape: autoqa/components/test_case_reviewer/core.py::TCReviewState
- Rubric: autoqa/prompts/single-test-aggregator-v4.jinja2
- Review objectives: autoqa/components/test_case_reviewer/review_objectives.yaml

## Assumptions and choices
- <Any product-specific simplifications>
- <Any rubric edge-case rulings>
- <Anything an evaluator should know before running ML metrics>
```

## Verification checklist (run before claiming done)

- ✓ All `req_id` values are unique and follow a consistent prefix.
- ✓ All `test_id` values are unique and follow a consistent pattern.
- ✓ Every `upstream_requirements` list has ≥1 entry.
- ✓ Requirements use SHALL / SHOULD / MAY appropriately.
- ✓ Technical specifications are realistic for the chosen product.
- ✓ Each output record validates against `TestCaseAssessment.model_validate(record["aggregated_assessment"])`.
- ✓ Every output's `evaluated_checklist` has exactly 5 items with ids matching
  `review_objectives.yaml` (expected_result_support, expected_result_spec_align,
  test_case_achieves, test_case_logical_sequence, test_case_setup_clarity).
- ✓ Every `partial=true` finding has `verdict="Yes"`. No `partial=true` with No.
- ✓ `overall_verdict="Yes"` iff every checklist verdict is `"Yes"` (deterministic
  check — fail loudly if any record violates this).
- ✓ For known-bads: at least one `evaluated_checklist[i].verdict == "No"`, and
  the failing item's id matches `primary_failure`.
- ✓ For yes-partials: ≥1 checklist item has `partial=true`, `overall_verdict="Yes"`,
  and the partial item's id is in `expected_partial_objectives`.
- ✓ For full-green: every `partial=false` and `overall_verdict="Yes"`.
- ✓ Across all known-bads, primary_failure distribution roughly matches the
  requested per-objective split.
- ✓ Spec_align rule cross-check: build `n_covered / n_total` from each output's
  coverage_analysis and confirm it matches the spec_align verdict + partial:
  all=Yes-no-partial, ≥1=Yes-partial, 0=No.
- ✓ inputs.jsonl line N corresponds to outputs.jsonl line N (same test_id).
- ✓ description.md numbers match the file row counts.

## Out of scope

- Running the pipeline against the generated inputs (use
  `tests/integration/test_tc_pipeline.py::test_tc_pipeline_parametrized_fanout`
  for that).
- Computing actual ML metrics — this skill produces the dataset; metric
  computation is downstream.
- Cross-domain mixed datasets — pick one domain per generation run.
- Hazard-traceable inputs — for hazard-driven datasets use the
  `hazard_risk_reviewer` schema instead.
- RTM-style (one-requirement-many-test-cases) data — use `generate-rtm-dataset`.
