# Synthetic Hazard Dataset — FluxPump 4000

## Domain & product
- Domain: Medical Device Software (SiMD, IEC 62304 / ISO 14971 / IEC 60601-2-24)
- Product: FluxPump 4000 — a Class II PCA infusion pump SiMD, IEC 62304 Class B
- Compliance frame: IEC 62304, ISO 14971, IEC 60601-2-24 (alarm requirements for infusion pumps)

## Class distribution
- Total records: 1
- Class: known-good (intended overall_verdict = "Yes" once the live LLM scores it)
- Failure-mode plant: none — both requirements have full functional + negative + boundary
  test coverage and the post-mitigation traceability is fully populated. This record is a
  smoke-test for the per-dimension hazard graph, not a classifier-evaluation set.

## Record summary
- Hazard: HAZ-PUMP-002 — Suppressed or delayed downstream-occlusion alarm
- Requirements (mitigations, 2):
    - REQ-PUMP-201 — priority-aware alarm queue with backpressure
    - REQ-PUMP-202 — audio+display driver heartbeat verification + redundant alarm path
- Test cases (4 total, 2 per requirement):
    - TC-PUMP-201-A (functional, REQ-PUMP-201)
    - TC-PUMP-201-B (boundary + negative, REQ-PUMP-201)
    - TC-PUMP-202-A (functional, REQ-PUMP-202)
    - TC-PUMP-202-B (negative, REQ-PUMP-202)
- Design docs (1): DD-PUMP-ALARM-001 (alarm subsystem architecture)

## Design intent (so the reviewer's H1-H5 verdicts can be sanity-checked)
- H1 Hazard Statement Completeness — should be "Yes": hazard / situation / sequence /
  function / harm / severity rationale are all populated and the chain is consistent.
- H2 Pre-Mitigation Risk — should be "Yes": severity Critical × probability Probable ×
  exploitability Likely → Unacceptable initial rating, all populated and consistent.
- H3 Risk Control Adequacy — should be "Yes": every step in the FSOE chain and every
  software_related_cause is controlled by a requirement (REQ-PUMP-201 covers Step 3 +
  cause #1; REQ-PUMP-202 covers Step 3 + cause #2). Each requirement should yield M1
  Functional = Yes via its functional TC.
- H4 Verification Depth — should be "Yes": REQ-PUMP-201 has both a boundary/negative
  burst test (TC-PUMP-201-B) and REQ-PUMP-202 has a fault-injection negative test
  (TC-PUMP-202-B). Software_related_causes is non-empty so "N-A" is not legitimate.
- H5 Residual Risk Closure — should be "Yes": every post-mitigation field is
  populated, traceability fields (sw_fmea_trace, sra_link, urra_item) are populated,
  and the probability downgrade Probable → Remote is supported by H4 = Yes.

## Schema references
- Input shape: autoqa/components/hazard_risk_reviewer/core.py::HazardRecord
- Pipeline: autoqa/components/hazard_risk_reviewer/pipeline.py::HazardReviewerRunnable
- Per-dimension prompts: autoqa/prompts/hazard_h{1,2,3,4,5}_evaluator-v1.jinja2 +
  hazard_final_assessor-v1.jinja2

## How to run
```bash
uv run python scripts/run_hazard_pipeline.py \
    tests/fixtures/generated/hazard_dataset/inputs.jsonl
```
The script writes outputs.jsonl + viewer_hz.html into the run directory under
logs/run-<ts>/ alongside hazard_graph.png.

## Statistical posture
N=1, so this is a smoke test, not an evaluation. For classifier-grade evaluation
of the hazard reviewer, generate ≥30 known-bads (≥6 per failing dimension across
H1-H5) plus ≥30 known-goods using the same domain pattern.

## Assumptions and choices
- Severity is graded Critical (not Catastrophic) because the dominant clinical
  scenario for this product is PCA pain management; the rationale field documents
  the grading.
- The OTS audio driver is named with a version pin so H1's "OTS software"
  consistency check has something concrete to evaluate.
- Both requirements use SHALL (mandatory). One concrete numeric threshold per
  requirement (100 alarms/s, 500 ms heartbeat, 1 s redundant-path activation) so
  H4 has surfaces to assess for boundary and negative testing depth.
