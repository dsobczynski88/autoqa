---
name: review-rtm-assessment
description: |
  Reformat a SynthesizedAssessment produced by autoqa/components/test_suite_reviewer
  into a reviewer-ready report with a binary Yes/No coverage verdict, SoP-mandatory
  findings separated from AI suggestions, inline test case text, and a JAMA link.
  Use when reviewing pipeline outputs against tests/fixtures/gold_dataset.jsonl
  records or any run artifact under logs/run-*/pipeline_state.json. Applies a fixed
  rubric (M1-M5 mandatory, S1-S5 suggestions) derived from reviewer VoC feedback.
---

# review-rtm-assessment

Reformat a single `SynthesizedAssessment` into a reviewer-ready report. Applies a
fixed rubric and emits markdown that drops the prose-style `coverage_assessment`
field in favor of bulleted mandatory findings vs. AI suggestions, inline test
cases, a JAMA link, and one binary Yes/No verdict.

This skill is **read-only**. It emits markdown to the conversation; it does not
write files, mutate pipeline state, or call the LLM pipeline.

## When to invoke

- A user asks to "review", "reformat", or "apply the rubric to" a pipeline output.
- A user references a pipeline state file (e.g. `logs/run-<ts>/pipeline_state.json`).
- A user references a requirement ID like `REQ-HC-012` in the context of reviewing
  coverage assessments.

## Invocation modes

Pick the first mode that matches what the user provided:

1. **State JSON path** — user gives a path, usually `logs/run-<ts>/pipeline_state.json`.
   Read it with the Read tool. It must contain `requirement`, `test_cases`,
   `test_suite`, `coverage_analysis`, `synthesized_assessment`.

2. **`--req <REQ-ID>`** — user gives a requirement ID. Look it up in
   `tests/fixtures/gold_dataset.jsonl` (one JSON record per line; match on
   `requirement.req_id`). The gold record supplies `requirement` and `test_cases`.
   If the user has not pasted a `synthesized_assessment`, run the rubric against
   the gold record's `description`/`rationale`/`expected_gap` fields as the
   stand-in assessment context.

3. **Inline paste** — user pastes a JSON blob with `requirement`, `test_cases`,
   and (optionally) `synthesized_assessment`. Parse and proceed.

If none match, ask the user which record or file to review. Do not guess.

## Inputs the skill consumes (schema reference)

From the pipeline state (see `autoqa/components/test_suite_reviewer/core.py`):

- `requirement`: `{req_id, text}`
- `test_cases`: list of `{test_id, description, setup, steps, expectedResults}`
- `test_suite.summary`: list of `SummarizedTestCase` — use as the canonical
  rendered list when available; fall back to `test_cases` otherwise
- `coverage_analysis`: list of `EvaluatedSpec` — one per decomposed spec, with
  `spec_id`, `covered_exists` (bool), and `covered_by_test_cases` (each entry
  carries its own per-TC `dimensions` list and `rationale`)
- `synthesized_assessment`: `{requirement, coverage_assessment, comments}` —
  the current prose output you are replacing

## Rubric

### Mandatory (SoP-gating)

Any `No` on a mandatory item flips the overall verdict to **No**. `N-A` does
not flip the verdict — use it only when the requirement genuinely has no
applicable surface for that dimension. Each finding may also carry
`partial: true` (only when `verdict == "Yes"`); a partial Yes still passes
SoP gating but signals that a reviewer should re-check that dimension —
surface it in commentary, do not treat it as a No.

- **M1 Functional** — at least one TC verifies the core positive behavior stated
  in the requirement.
- **M2 Negative** — at least one TC verifies invalid input, error condition, or
  failure mode. `N-A` only if the requirement has no validation surface or
  failure modes (rare).
- **M3 Boundary** — at least one TC probes a threshold, numeric limit, or
  discrete role/tag transition. `N-A` when the requirement has no such surface
  (example: REQ-TL-008, a passive UI presence check with no numerical variables).
- **M4 Spec Coverage** — every decomposed spec has ≥1 TC with `covered_exists=true`
  in `coverage_analysis`. Read directly from the pipeline state; when absent,
  infer from the requirement text.
- **M5 Terminology** — TC vocabulary aligns with requirement vocabulary. Flag
  semantic drift where a TC reframes a restricted/prohibited behavior as
  standard, or renames a role/tag from the requirement.

### AI suggestions (non-gating)

Advisory commentary. Never flips the verdict. Each item is either a specific
comment with TC IDs cited, or `"none"`.

- **S1 Input variety** — additional units of measure, magnitudes, or equivalence
  classes worth exercising on the same TCs.
- **S2 Threshold ordering** — pre-event checks not currently tested (e.g., alert
  *before* a dispense action, not only on/after).
- **S3 UI presence** — explicit assertions about UI element visibility that
  should be repeated across all paths.
- **S4 Indirect access** — alternate entry points, API-level access, or
  workarounds not covered by the current TC steps.
- **S5 Requirement split** — compound requirements that would be easier to
  verify if decomposed into independently-stated requirements.

### Worked examples (drawn from reviewer feedback on gold_dataset.jsonl)

| Item | Source | Pattern to detect |
|------|--------|-------------------|
| M5 | TC-039-01 | Req says "restricted" → TC says "standard allocation". Flag as No. |
| M4 | REQ-HC-039 | Decomposed spec "tag patient as Emergency Trauma" has no covering TC. |
| S1 | TC-HC-012A/B | Dosage tests use only mg/kg/day; add tests in mg, g, or mcg. |
| S2 | REQ-HC-028 | "Alert at stock ≤ 10" — no test verifies alert *fires* at stock=8 *before* dispense. |
| S3 | REQ-SC-202 | "Emergency Break-Glass" button presence not asserted in TC-202-01/02. |
| S4 | REQ-SC-202 | Indirect note access paths (direct URL, API, report export) not tested. |
| S5 | REQ-HC-012 | "trigger warning + require justification" could be split into two requirements. |

## JAMA link

Template: `{JAMA_BASE_URL}/perspective.req#/items/{req_id}`

- Read `JAMA_BASE_URL` from the environment. In practice, check `.env` in the
  project root with Read.
- If unset, emit `jama://item/{req_id}` as the href and add a
  `> **Note:** JAMA_BASE_URL not configured — link is a placeholder.`
  admonition immediately below the link.

## Output template

Emit exactly this structure. Every section is required; use `N-A` or `none`
rather than omitting a section.

```markdown
# Requirement {req_id}
[Open in JAMA]({JAMA_BASE_URL}/perspective.req#/items/{req_id})

**Text:** {requirement.text}

## Coverage Verdict: **Yes** | **No**

## Test Cases (inline)
### {test_id} — {description}
- **Setup:** {setup}
- **Steps:**
  1. {step 1}
  2. {step 2}
- **Expected:**
  1. {expected 1}
  2. {expected 2}

(repeat per test case)

## Mandatory Findings (SoP-gating)
- **[M1 Functional]** Yes/No — {one-line rationale citing TC IDs}
- **[M2 Negative]** Yes/No/N-A — {one-line rationale}
- **[M3 Boundary]** Yes/No/N-A — {one-line rationale}
- **[M4 Spec Coverage]** Yes/No — {list only the uncovered spec_ids; "all covered" if Yes}
- **[M5 Terminology]** Yes/No — {specific mismatches, or "aligned"}

## AI Suggestions (non-gating)
- **[S1 Input variety]** {comment with TC IDs, or "none"}
- **[S2 Threshold ordering]** {comment, or "none"}
- **[S3 UI presence]** {comment, or "none"}
- **[S4 Indirect access]** {comment, or "none"}
- **[S5 Requirement split]** {comment, or "none"}
```

## Execution steps

1. Resolve inputs per the invocation-modes section. Read the state JSON or
   gold record.
2. Render the `# Requirement` header and JAMA link.
3. Render each test case inline using `test_suite.summary` when available,
   otherwise the raw `test_cases` list. Preserve step numbering; do not
   paraphrase setup/steps/expected.
4. Evaluate each mandatory item M1-M5 against the requirement + TCs +
   `coverage_analysis`. Cite TC IDs in the rationale.
5. Evaluate each suggestion S1-S5; default to `"none"` when nothing applies.
   Be specific — vague suggestions are not useful.
6. Compute the verdict: `Yes` iff every M1-M5 is `Yes` or `N-A`.
7. Emit the completed template in one message. No preamble, no trailing summary.

## Out of scope

- Modifying the pipeline schema, prompts, or LangGraph nodes. This is a
  review-time reformatter; upstream changes are a separate task.
- Running the pipeline itself. The user is expected to have a pipeline state
  artifact or gold record on hand.
- Writing files. The skill emits markdown to the conversation only.
