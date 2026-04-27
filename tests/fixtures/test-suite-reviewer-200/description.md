# Synthetic RTM Dataset — CGM SaMD (200 records)

## Domain & product
- **Domain**: Medical-device software (Software as a Medical Device, IEC 82304 health software).
- **Product**: Continuous Glucose Monitor (CGM) SaMD — a Class II SaMD comprising a wearable
  transmitter, mobile app, and cloud sync. Compliance frame: IEC 62304 Class B (non-life-supporting),
  ISO 14971 risk management, FDA 21 CFR Part 820.30 design controls.
- **20 archetypes** covering: hypo/hyper alerts, calibration range, sensor warm-up, battery-low,
  BLE pairing, cloud sync, audit retention, pump linking, predictive alert, caregiver SMS,
  time-in-range, sensor expiry, CSV export size, multi-account cap, TLS minimum, firmware battery
  gate, severe-hypo emergency, trend arrow, pairing-code expiry.

## Class distribution
- **Known good** (label=1, overall_verdict=Yes): 100 records.
- **Known bad**  (label=0, overall_verdict=No):  100 records.
- **Total**: 200 records.

## Failure-mode distribution (known bads)
- M1 Functional No: 20 records.
- M2 Negative No:   20 records.
- M3 Boundary No:   20 records.
- M4 Spec Coverage No: 20 records.
- M5 Terminology No:   20 records.
- (Sum = 100; matches known-bad count.)

## Statistical posture (Regime 1 — overall accuracy CI)
- Per-class n = 100 (good) and 100 (bad). Total n = 200.
- 95% confidence interval on overall accuracy at 50/50 prior:
  margin of error ε ≈ sqrt(0.96 / n_per_class) ≈ ±10.0% (worst case, p = 0.5).
- Per-rubric-cell coverage: ~20 known-bads per failing dimension. With
  ≥30 per cell as a working floor for stable per-rubric F1/recall, this dataset is
  **just below** that floor (~20/cell). Treat per-rubric metrics as exploratory; overall
  metrics are stable at ±10%.

## Schema references
- **Input shape**: matches `tests/fixtures/gold_dataset.jsonl` (one record per line). Required
  keys: requirement, test_cases, rationale, expected_gap, description.
- **Output shape**: matches `RTMReviewState` from `autoqa/components/test_suite_reviewer/core.py`.
  Required keys: requirement, test_cases, decomposed_requirement, test_suite, coverage_analysis,
  synthesized_assessment. Each output also carries `_label` (0 or 1) and `_failing_dim` (M1-M5
  or null) for ML-evaluation convenience.
- **Rubric**: M1-M5 mandatory findings as defined in `autoqa/prompts/synthesizer-v6.jinja2`.
  M2 and M3 may be N-A; M1, M4, M5 are always Yes/No. `overall_verdict = "Yes"` iff every
  finding's verdict is in `{Yes, N-A}`.

## Assumptions and choices
- Every archetype has both a validation surface AND a numeric threshold. This ensures M2 and
  M3 can be exercised as failing dimensions on any archetype (none collapse to N-A in the
  ground-truth output for known-bads).
- Test-case `setup` strings include realistic SaMD specifics (firmware version, user role,
  sensor lot, BLE state) so reviewers can verify reproducibility detail.
- Test-case `dimensions` labels are deterministic per the archetype TC blueprints; they
  directly drive the M1-M5 verdicts via the rubric. The output does NOT depend on any LLM
  call — it is the **ground-truth assessment** a faithful synthesizer should emit.
- For known-bads, the deliberate gap is encoded in (a) the input's `expected_gap` field
  ("functional" / "negative" / "boundary" / "coverage" / "terminology") and (b) the
  output's matching `_failing_dim` and synthesized `mandatory_findings[].verdict="No"` row.
- Vocabulary mismatches in M5 known-bads are not literally introduced into the test text;
  the failing dimension is set in the ground-truth output. To exercise M5 detection in an
  LLM-driven evaluation, an extension pass could rewrite TC text with synonym substitutions.

## How to use
- **Pipeline-as-classifier evaluation**: run inputs.jsonl through the
  `test_suite_reviewer` pipeline; compute accuracy / F1 of the predicted overall_verdict
  against the ground-truth `synthesized_assessment.overall_verdict` in outputs.jsonl
  (or against `_label`).
- **Per-rubric metric evaluation**: compare each predicted `mandatory_findings[i].verdict`
  against the ground-truth at index i.
- **Power audit**: this dataset gives ±10% CI on overall accuracy. To tighten to ±5%,
  scale to ~800 records (re-run the generator with 5 param_sets per archetype expanded to
  ~20, or add additional archetypes).
