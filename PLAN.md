# AutoQA criteria updates — coverage_evaluator v6, synthesizer v5, viewer

## Context

Reviewers (VoC) flagged three problems with the current pipeline output and viewer:

1. **`coverage_rationale` is redundant** in the coverage_evaluator output — every entry of `covered_by_test_cases` already carries a per-TC `rationale`, so the top-level `coverage_rationale` field repeats information the reviewer can already see and bloats the LLM call.
2. **The synthesized rubric is binary green/red** — when a dimension has *some* coverage but is incomplete, the model is forced to either award a green Yes (overstating) or a red No (understating). Reviewers want a third visual tier ("Yellow / partial Yes") that still passes SoP gating but signals "this needs another look." Rationales and clarification questions also currently leak spec-IDs (e.g. `"REQ-HC-039-2 not covered"`); reviewers want them framed at the *requirement* level since the spec IDs are an internal pipeline artifact, not something the reviewer is tracking.
3. **The viewer doesn't reflect any of this yet** — it still renders a `coverage_rationale` column, has no Yellow styling, and has no inline help explaining what M1–M5 actually mean.

The goal: ship `coverage_evaluator-v6.jinja2` and `synthesizer-v5.jinja2`, extend `MandatoryFinding` with a `partial: bool` field, and update the viewer to drop the dead column, paint partial-Yes findings Yellow, and add a "?" tooltip on the Dimension column.

## Decisions confirmed with user

- **Versioning:** Bump to new files. Latest coverage_evaluator on disk is `v5` → create `v6`. Latest synthesizer on disk is `v4` → create `v5`. Old versions stay as historical references.
- **Partial encoding:** Add `partial: bool = False` to `MandatoryFinding`. `verdict` Literal stays `Yes/No/N-A`. Yellow is a viewer-side rendering of `verdict == "Yes" AND partial == True`.

## Critical files to modify

| File | Change |
|---|---|
| `autoqa/prompts/coverage_evaluator-v6.jinja2` | **NEW.** Copy of v5 minus the `coverage_rationale` field in schema, example, and instructions. |
| `autoqa/prompts/synthesizer-v5.jinja2` | **NEW.** Copy of v4 with: partial-Yes logic per M1–M5, requirement-level rationales (no spec-ID citations), requirement-level clarification questions, updated JSON schema with `partial` field. |
| `autoqa/components/test_suite_reviewer/core.py` | Remove `coverage_rationale` from `EvaluatedSpec`. Add `partial: bool = Field(default=False, ...)` to `MandatoryFinding`. |
| `autoqa/components/test_suite_reviewer/nodes.py` | Bump factory defaults: `make_coverage_evaluator` → `coverage_evaluator-v6.jinja2`; `make_synthesizer_node` → `synthesizer-v5.jinja2`. |
| `autoqa/viewer/template.py` | Drop `coverage_rationale` column from the `openSpecs()` modal. Add Yellow CSS (`--warn`, `.verdict-Yellow`, `.chip-Yellow`). In `renderLeft()` JS: pick chip class from `partial`; recompute overall-verdict badge as Yellow when `overall_verdict == "Yes"` AND any finding has `partial == true`. Add a "?" help icon next to the "Dimension" `<th>` that opens a modal listing the M1–M5 criteria. |
| `.claude/skills/review-rtm-assessment/SKILL.md` | Drop the `coverage_rationale` reference from the "Inputs" schema section (line 59). Add a one-line note that `mandatory_findings[i].partial` exists and means "Yes-but-partial; treat as Yes for gating, surface in commentary." |
| `.claude/skills/visualize-batch-outputs/SKILL.md` | Drop `coverage_rationale` from the EvaluatedSpec shape (line 68). Update the "Coverage Assessment" bullet to mention Yellow for partial-Yes. Add a sentence about the new "?" help affordance. |

## Reusable code/patterns to leverage

- `render_prompt(template_name, **kwargs)` in `autoqa/utils.py` — already used by every factory; no new wiring needed for the new prompt files.
- `template.py`'s existing `escapeHTML`, `openModal()`, `closeModal()`, and `.modal` CSS — reuse these for the new "?" criteria popup; do not invent a second tooltip system.
- CSS variable pattern at `template.py:11–15` — add `--warn` / `--chip-warn` colors there and use them via `var(--warn)` to stay consistent.
- Per-finding chip class is already computed from `f.verdict` at `template.py:148`; extend that to `f.verdict === "Yes" && f.partial ? "Yellow" : f.verdict` in one place.

## Implementation details

### 1. `coverage_evaluator-v6.jinja2`

Start from `coverage_evaluator-v5.jinja2` verbatim, then:
- **Remove** the `coverage_rationale` line from the JSON Output Schema (last field).
- **Remove** the `coverage_rationale` line from the in-context Expected Output example.
- **Remove** the Step 4 ("Coverage Rationale") instruction in the Steps block.
- **Edit** the Narrowing constraint that refers to `coverage_rationale` — rephrase to point at the per-`covered_by_test_cases[i].rationale` field instead, so the V&V justification requirement still applies but at the per-TC granularity.

### 2. `synthesizer-v5.jinja2`

Start from `synthesizer-v4.jinja2` verbatim, then:
- **Add `partial`** to each `mandatory_findings[i]` schema entry: `"partial": "boolean (true ONLY when verdict='Yes' AND coverage is incomplete in some way; false otherwise; always false when verdict='No' or 'N-A')"`.
- **New rule block** under "The Rubric": "Partial-Yes — set `partial: true` when the dimension has covering test cases but coverage of the requirement is incomplete (e.g. only some validation surfaces are tested for M2; only one of multiple thresholds is probed for M3; some specs covered but others have weak/peripheral coverage for M4). The verdict still resolves to `Yes` for SoP gating; `partial` is the visual signal that a reviewer should re-check."
- **Rewrite the Citations and brevity block:**
  - Each `rationale` is ONE SENTENCE.
  - When `partial: true`, the rationale must explain *what is covered AND what is missing at the requirement level* (e.g. *"functional path verified but error-handling for invalid timestamps not exercised"*) — **do NOT cite spec_ids in the rationale prose**.
  - When `verdict: "No"`, rationale describes the gap at the requirement level (e.g. *"no boundary tests for the dosage threshold"*) — **do NOT list spec_ids in the rationale prose**.
  - For M4: when verdict=No, `uncovered_spec_ids` still carries the IDs (machine-readable), but the rationale itself is requirement-level prose (e.g. *"emergency-trauma tagging path is untested"*).
- **Rewrite the `clarification_questions` block:** examples and constraints must produce questions phrased at the *requirement* level. Strip the example *"Should TC-{id} be re-scoped to cover spec {spec_id}…"* and replace with one like *"Are emergency-trauma tagging paths verified by a separate requirement outside this suite?"* The "one question per distinct ambiguity" rule stays.
- **Update the JSON schema example** at the bottom to include `"partial": false` on every `mandatory_findings[i]`.

### 3. `core.py` model edits

```python
# EvaluatedSpec — remove coverage_rationale entirely
class EvaluatedSpec(BaseModel):
    spec_id: str
    covered_exists: bool
    covered_by_test_cases: List[CoveringTestCase]
    # (coverage_rationale field deleted)

# MandatoryFinding — add partial
class MandatoryFinding(BaseModel):
    code: Literal["M1", "M2", "M3", "M4", "M5"]
    dimension: Literal["Functional", "Negative", "Boundary", "Spec Coverage", "Terminology"]
    verdict: VerdictNA
    partial: bool = Field(
        default=False,
        description=(
            "True ONLY when verdict='Yes' AND coverage is incomplete at the "
            "requirement level. Always False when verdict is No or N-A. "
            "Drives Yellow rendering in the viewer; does NOT affect SoP gating."
        ),
    )
    rationale: str
    cited_test_case_ids: List[str] = Field(default_factory=list)
    uncovered_spec_ids: List[str] = Field(default_factory=list)
```

No change to `overall_verdict` semantics. The viewer derives "overall is partial" by scanning `mandatory_findings` itself — keeping the data model minimal.

### 4. `nodes.py` factory defaults

Two one-line bumps:
- `make_coverage_evaluator(... prompt_template: str = "coverage_evaluator-v6.jinja2", ...)`
- `make_synthesizer_node(... prompt_template: str = "synthesizer-v5.jinja2", ...)`

### 5. `viewer/template.py` edits

**CSS additions** in `:root` (around line 12):
```css
--warn: #fff4cc;        /* light yellow background */
--chip-warn: #b58105;   /* dark amber for chip */
```

Add CSS classes alongside existing verdict/chip styles:
```css
.verdict-Yellow { background: var(--warn); color: #6b4f00; }
.chip-Yellow { background: var(--chip-warn); }
```

Add a small help icon style:
```css
.help-icon {
  display: inline-block; width: 16px; height: 16px; line-height: 16px;
  text-align: center; border-radius: 50%; background: #e3e3e3;
  color: var(--mute); font-size: 11px; font-weight: 700; cursor: pointer;
  margin-left: 6px; vertical-align: middle;
}
.help-icon:hover { background: var(--accent); color: #fff; }
```

**JS changes in `renderLeft()`:**
- For each `f` in `mandatory_findings`: compute `chipClass = (f.verdict === "Yes" && f.partial) ? "Yellow" : f.verdict`. Use `chipClass` in `chip chip-${chipClass}`.
- For overall verdict: compute `overallClass = (sa.overall_verdict === "Yes" && (sa.mandatory_findings || []).some(f => f.partial)) ? "Yellow" : sa.overall_verdict`. Use it in `verdict-badge verdict-${overallClass}`. Keep the displayed text as the literal `overall_verdict` value ("Yes"/"No") — color is the only signal; do NOT relabel as "Partial."
- Change the findings table header from `<th>Dimension</th>` to `<th>Dimension <span class="help-icon" onclick="openCriteriaHelp()">?</span></th>`.

**Drop `coverage_rationale` rendering** in `openSpecs()`:
- Remove the `<td style="max-width:320px">${escapeHTML(a?.coverage_rationale ?? "")}</td>` cell (around line 244).
- Remove the `<th>Coverage rationale</th>` column header from the same `openSpecs()` table (around line 250).

**Add `openCriteriaHelp()`** — a new top-level JS function that calls `openModal(...)` with a static HTML block of the M1–M5 criteria. Source the prose from the `synthesizer-v5.jinja2` "The Rubric" section so wording stays canonical:
```
M1 Functional — at least one TC verifies the core positive behavior of the requirement (happy path).
M2 Negative — at least one TC exercises invalid input, an error condition, or a failure mode. N-A only when the requirement has no validation surface.
M3 Boundary — at least one TC probes a threshold, numeric limit, or role/tag transition. N-A when there is no such surface.
M4 Spec Coverage — every decomposed spec has at least one covering test case.
M5 Terminology — test-case vocabulary aligns with the requirement (no semantic drift, no renamed roles/tags).

Yellow = "Yes, but partial" — coverage exists but is incomplete; reviewer should re-check.
```

### 6. SKILL.md updates

- `review-rtm-assessment`: in the "Inputs" reference list, change `EvaluatedSpec` line to drop `coverage_rationale`. Add a one-line note under "Mandatory" that `mandatory_findings[i].partial` is informational only — `Yes` (partial=true) still passes SoP gating.
- `visualize-batch-outputs`: in the "Expected input shape" section, remove `coverage_rationale` from the EvaluatedSpec line. In the "Coverage Assessment" bullet, change `(Yes = green / No = orange)` to `(Yes = green / Yes-partial = yellow / No = orange)`. Add one bullet under it noting the "?" help affordance on the Dimension column opens an M1–M5 criteria summary.

## What is intentionally NOT changing

- `Verdict` and `VerdictNA` Literal types stay as-is — Yellow is purely viewer-side.
- `overall_verdict` aggregation rule stays binary Yes/No (any No flips to No; partial does not flip).
- Older prompt versions (v2/v3/v4/v5) stay on disk as historical references.
- `tests/fixtures/coverage_evaluator_cases.jsonl` is untouched. Pydantic ignores extra keys by default, so fixture lines that still include `coverage_rationale` will still parse against the trimmed `EvaluatedSpec`. If a unit test asserts on the field's presence, it must be updated; otherwise no change.
- No backwards-compatibility shim for `coverage_rationale`. It is being removed cleanly per CLAUDE.md guidance ("don't add backwards-compatibility hacks").

## Verification plan

1. **Unit tests:** `uv run pytest tests/unit/ -v`. These don't hit the LLM; verify the model edits don't break parsing of existing fixtures. Update any unit assertion that explicitly reads `coverage_rationale`.
2. **Single integration test:** `uv run pytest tests/integration/test_pipeline.py::test_pipeline_full_state -m integration -s` — confirms one full run produces a `SynthesizedAssessment` containing `partial` fields and an `EvaluatedSpec` with no `coverage_rationale`.
3. **Batch + viewer E2E:** `uv run pytest tests/integration/test_pipeline.py::test_pipeline_parametrized -m integration -s`. The session teardown auto-generates `viewer.html` next to the run's `outputs.jsonl`. Open it in a browser and verify, on at least one record where the LLM returned `partial: true`:
   - The relevant M-row chip renders Yellow.
   - The "Overall verdict" badge renders Yellow.
   - The "?" icon next to the "Dimension" header opens the criteria modal.
   - The "Decomposed specs & coverage analysis" modal no longer has a "Coverage rationale" column.
   - Rationales and clarification questions read as requirement-level prose, with no `REQ-XXX-N` spec IDs in the visible text.
4. **Skill self-check:** Invoke `review-rtm-assessment` against one `logs/run-*/pipeline_state.json` from step 3 and confirm the markdown output renders cleanly with the new schema.

## Order of operations

1. Write `coverage_evaluator-v6.jinja2` and `synthesizer-v5.jinja2` (no code is broken yet — old prompts still wired).
2. Edit `core.py` models. Now the in-flight schema is the new one.
3. Edit `nodes.py` factory defaults to point at v6/v5.
4. Edit `viewer/template.py` (CSS, JS, criteria help modal).
5. Edit both SKILL.md files.
6. Run unit tests; fix any explicit `coverage_rationale` assertions.
7. Run one integration test, then the parametrized batch.
8. Open `viewer.html`, walk through 2–3 records, sanity-check Yellow rendering and the "?" tooltip.
