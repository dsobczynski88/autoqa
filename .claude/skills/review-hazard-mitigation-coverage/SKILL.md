---
name: review-hazard-mitigation-coverage
description: |
  Reformat a HazardPackage (one or more HazardRecord items, each bundling
  requirements, test cases, and design docs) into a reviewer-ready hazard
  mitigation coverage report. Applies a fixed rubric (H1-H5 mandatory, A1-A5
  suggestions) grounded in ISO 14971 / IEC 62304 / IEC 61508 to verdict whether
  software risk controls and their verification provide reasonable assurance of
  safety. Use when reviewing hazard register entries, FMEA-traced requirements,
  or any artifact matching the HazardRecord schema. Complements
  review-rtm-assessment (which evaluates functional/negative/boundary coverage
  of a single requirement, not hazard mitigation).
---

# review-hazard-mitigation-coverage

Reformat a `HazardPackage` into a reviewer-ready hazard mitigation coverage
report. Applies a fixed rubric grounded in ISO 14971 / IEC 62304 / IEC 61508
and emits markdown: a rollup table across hazards, then per-hazard sections
with the risk profile, traced controls, mandatory H1-H5 findings, A1-A5
advisory commentary, and a single Adequate/Partial/Inadequate verdict.

This skill is **read-only**. It emits markdown to the conversation; it does not
write files, mutate pipeline state, or call the LLM pipeline. It is a sibling
to `review-rtm-assessment`: that skill verdicts a single requirement's
functional/negative/boundary coverage; this one verdicts a hazard's risk
controls and verification evidence.

## When to invoke

- A user asks to "review", "assess", or "verdict" hazard mitigation, risk
  controls, or residual risk for a hazard or batch of hazards.
- A user references a hazard ID (e.g. `HAZ-001`), a hazard register file, or
  pastes a JSON object matching the `HazardRecord` schema.
- A user asks for an ISO 14971 / IEC 62304 coverage assessment, FMEA gap
  review, or "reasonable assurance of safety" check on traced requirements.

## Invocation modes

Pick the first mode that matches what the user provided:

1. **Path to a hazard package file** — user gives a path to a `.json` file
   containing either a `HazardPackage` (`{"hazards": [...]}`) or a bare array
   of `HazardRecord`s (matching the JSON schema below). Read it with the Read
   tool.

2. **Inline paste** — user pastes a JSON blob with one or more `HazardRecord`s.
   Parse and proceed.

3. **`--hazard-id <ID>`** — user gives a hazard ID against a package already in
   conversation context (loaded earlier in the same session). Filter the
   package to that one record and proceed.

If none match, ask the user which hazard or file to review. Do not guess.

## Inputs the skill consumes (schema reference)

The user supplies a `HazardPackage`. The Pydantic model and JSON schema below
are authoritative — note that `requirements` is `min_items=1`, all top-level
HazardRecord string fields are required (use empty string `""` if unknown),
and `test_cases` / `design_docs` may be empty lists.

```python
class Requirement(BaseModel):
    req_id: str            # Unique requirement identifier
    text: str              # Requirement description text

class TestCase(BaseModel):
    test_id: str           # Unique test case identifier
    description: str       # High-level test case description
    setup: str             # Preconditions and environment setup
    steps: str             # Ordered test execution steps
    expectedResults: str   # Expected outcomes

class DesignDocument(BaseModel):
    doc_id: str            # Unique design document identifier
    name: str              # Design document title
    description: str       # Design document description

class HazardRecord(BaseModel):
    hazard_id: str
    hazardous_situation_id: str
    hazard: str
    hazardous_situation: str
    function: str
    ots_software: str                         # OTS software component if applicable
    hazardous_sequence_of_events: str
    software_related_causes: str
    harm_severity_rationale: str              # External-risk-control rationale
    harm: str
    severity: str
    exploitability_pre_mitigation: str        # Cyber exploitability, pre
    probability_of_harm_pre_mitigation: str   # Software / use-related, pre
    initial_risk_rating: str
    risk_control_measures: str                # Inherent safety + protective + IFS
    demonstration_of_effectiveness: str       # Trace to verification evidence
    severity_of_harm_post_mitigation: str
    exploitability_post_mitigation: str
    probability_of_harm_post_mitigation: str
    final_risk_rating: str
    new_hs_reference: str                     # Downstream Hazardous Situation ID
    sw_fmea_trace: str
    sra_link: str
    urra_item: str
    residual_risk_acceptability: str          # Per GQP-10-02 / RMR
    requirements: List[Requirement]           # min_items=1
    test_cases: List[TestCase]
    design_docs: List[DesignDocument]

class HazardPackage(BaseModel):
    hazards: List[HazardRecord]
```

The shared `Requirement` and `TestCase` shapes match
`autoqa/components/test_suite_reviewer/core.py`, so a hazard's traced TCs can
be cross-referenced with the same identifiers as `review-rtm-assessment`.

## Rubric

### Mandatory (SoP-gating)

Each H item carries one of: **Adequate / Partial / Inadequate** (plus `N-A`
only on H4). Compute the overall hazard verdict:

- **Adequate** iff every H1-H5 is `Adequate` or `N-A`
- **Inadequate** if any H is `Inadequate`
- **Partial** otherwise (any `Partial` and no `Inadequate`)

`Partial` is not a soft pass — it tells a reviewer to re-check that dimension
before sign-off. `N-A` does not flip the verdict.

| Item | Dimension | Source fields | Criteria |
|---|---|---|---|
| **H1** | Hazard Statement Completeness | `hazard`, `hazardous_situation`, `hazardous_sequence_of_events`, `harm`, `function` | Chain is populated, internally consistent, traceable from hazard → situation → sequence → harm. |
| **H2** | Pre-Mitigation Risk Characterization | `severity`, `probability_of_harm_pre_mitigation`, `exploitability_pre_mitigation`, `initial_risk_rating`, `harm_severity_rationale` | Severity, probability, and exploitability all populated; rationale present; initial rating is internally consistent with the matrix. |
| **H3** | Risk Control Adequacy (requirements coverage) | `risk_control_measures`, `software_related_causes`, `requirements[]` | Every step in `hazardous_sequence_of_events` and every entry in `software_related_causes` has ≥1 requirement that controls/blocks it. Requirements are unambiguous and address emergency, invalid, and prohibited states (ISO 14971 §6.2 — not just nominal behavior). |
| **H4** | Verification Depth (test coverage of controls) | `demonstration_of_effectiveness`, `test_cases[]` | Each control identified in H3 has ≥1 TC that exercises the **hazardous** path — not just nominal flow. Look for fault-injection, boundary, and negative dimensions. `demonstration_of_effectiveness` is consistent with the listed `test_cases`. `N-A` only when `software_related_causes` indicates no software-related cause. |
| **H5** | Residual Risk Closure | `severity_of_harm_post_mitigation`, `probability_of_harm_post_mitigation`, `exploitability_post_mitigation`, `final_risk_rating`, `residual_risk_acceptability`, `sw_fmea_trace`, `sra_link`, `urra_item` | Post-mitigation values populated; acceptability rationale present; the downgrade from initial → final risk is supported by the verification evidence in H4 (no unjustified probability drop); traceability fields populated. |

Each finding emits: verdict, one-line rationale, **cited** `req_id`s and
`test_id`s, and (for H3/H4) a list of unblocked sequence steps or unverified
controls.

### AI suggestions (non-gating)

Advisory commentary. Never flips the verdict. Each item is either a specific
comment with `req_id` / `test_id` / `doc_id` cited, or `"none"`.

- **A1 Architectural Isolation / SOUP** — when `ots_software` is populated,
  flag single-point-of-failure risk; comment on segregation of safety-critical
  paths from non-safety code if inferable from `function` + `design_docs`.
- **A2 Sequence Gap** — specific events in `hazardous_sequence_of_events` that
  no requirement *or* test case breaks. Quote the unblocked step verbatim.
- **A3 Verification Type Mix** — note when `test_cases` only exercise functional
  happy paths; recommend specific fault-injection / boundary / negative TCs.
- **A4 Cross-Hazard Dependencies** — when `new_hs_reference` is populated,
  surface the downstream hazard and whether residual risk is inherited.
- **A5 Remediation Recommendations** — concrete, actionable engineering steps
  to close each `Inadequate` or `Partial` H finding (new requirements, new TCs
  of a specific dimension, architectural changes, additional SOUP analysis).

### Worked examples

| Item | Pattern → Verdict |
|------|---|
| H1 | `hazard` and `harm` populated but `hazardous_sequence_of_events` is empty → **Partial**. The chain hazard → situation → harm is traceable but the causal sequence is missing. |
| H3 | `software_related_causes` lists "timer ISR fails to fire" but no requirement in `requirements[]` mandates a watchdog or independent shutoff → **Inadequate**. Cite the unblocked cause. |
| H4 | One TC verifies the alert displays at the threshold; no TC injects sensor drift, voltage spike, or stuck-at faults → **Partial**. Functional path covered, fault injection missing. |
| H4 | `software_related_causes` = "none — purely mechanical hazard" → **N-A**. |
| H5 | `probability_of_harm_pre_mitigation` = "Probable", `probability_of_harm_post_mitigation` = "Remote", but the only test cases are functional happy paths → **Inadequate**. The probability downgrade is not supported by evidence in H4. |
| A1 | `ots_software` = "FreeRTOS 10.4.3", `function` = "motor control loop" → flag single-point-of-failure risk; recommend SOUP failure-mode analysis or hardware-level interlock. |
| A2 | Sequence step "UI remains active while pump continues at max rate" not blocked by any requirement or TC → quote it verbatim under A2. |

## Traceability links

`sra_link`, `sw_fmea_trace`, `urra_item`, and `new_hs_reference` are external
system references — render them as inline code chips, not URLs. Do not
template a base URL (unlike `review-rtm-assessment`'s JAMA link, hazard data
typically spans multiple systems). If a field is empty, render `—`.

## Output template

For a `HazardPackage` with multiple records, emit a rollup table first, then
one full section per hazard. For a single hazard, skip the rollup. Every
section is required; use `N-A` or `"none"` rather than omitting a section.

````markdown
# Hazard Mitigation Coverage Review

## Rollup ({N} hazards)
| Hazard | Verdict | Initial → Final Risk | Worst Finding |
|---|---|---|---|
| `{hazard_id}` — {hazard} | Adequate/Partial/Inadequate | {initial_risk_rating} → {final_risk_rating} | H{n}: {one-line summary} |

(repeat per hazard)

---

# Hazard `{hazard_id}` — {hazard}

**Hazardous Situation (`{hazardous_situation_id}`):** {hazardous_situation}
**Function:** {function} | **OTS Software:** {ots_software or "none"}

## Sequence of Events
{hazardous_sequence_of_events}

**Software-related causes:** {software_related_causes}

## Risk Profile
| Stage | Severity | Probability of Harm | Exploitability | Risk Rating |
|---|---|---|---|---|
| Pre-mitigation  | {severity} | {probability_of_harm_pre_mitigation} | {exploitability_pre_mitigation} | {initial_risk_rating} |
| Post-mitigation | {severity_of_harm_post_mitigation} | {probability_of_harm_post_mitigation} | {exploitability_post_mitigation} | {final_risk_rating} |

**Harm:** {harm} — *{harm_severity_rationale}*

## Risk Control Measures
{risk_control_measures}

**Demonstration of effectiveness:** {demonstration_of_effectiveness}

## Linked Artifacts

**Requirements ({len}):**
- `{req_id}` — {text}

(repeat per requirement)

**Test cases ({len}):**
### `{test_id}` — {description}
- **Setup:** {setup}
- **Steps:**
  1. {step 1}
  2. {step 2}
- **Expected:**
  1. {expected 1}
  2. {expected 2}

(repeat per test case; preserve step numbering, do not paraphrase)

**Design docs ({len}):**
- `{doc_id}` — *{name}* — {description}

**Traceability:** SW-FMEA=`{sw_fmea_trace}` · SRA=`{sra_link}` · URRA=`{urra_item}` · New-HS=`{new_hs_reference or "—"}`

## Mitigation Coverage Verdict: **Adequate** | **Partial** | **Inadequate**

## Mandatory Findings (SoP-gating)
- **[H1 Hazard Statement Completeness]** Adequate/Partial/Inadequate — {one-line rationale}
- **[H2 Pre-Mitigation Risk]** Adequate/Partial/Inadequate — {one-line rationale}
- **[H3 Risk Control Adequacy]** Adequate/Partial/Inadequate — citing `REQ-…`; unblocked causes/steps: {list, or "none"}
- **[H4 Verification Depth]** Adequate/Partial/Inadequate/N-A — citing `TC-…`; unverified controls: {list, or "none"}
- **[H5 Residual Risk Closure]** Adequate/Partial/Inadequate — {one-line rationale}

## AI Suggestions (non-gating)
- **[A1 Architectural Isolation / SOUP]** {comment cit. `doc_id` / `req_id`, or "none"}
- **[A2 Sequence Gap]** {comment quoting unblocked step, or "none"}
- **[A3 Verification Type Mix]** {comment cit. `TC-…`, or "none"}
- **[A4 Cross-Hazard Dependencies]** {comment cit. `new_hs_reference`, or "none"}
- **[A5 Remediation Recommendations]** {actionable steps, or "none"}

## Residual Risk Acceptability (per GQP-10-02 / RMR)
{residual_risk_acceptability}
````

## Execution steps

1. Resolve inputs per the invocation-modes section. Read the package file or
   parse the inline paste; normalize a bare array into `{"hazards": [...]}`.
2. If multiple hazards, emit the rollup table first.
3. For each hazard:
   a. Render the header, sequence of events, risk profile table, and risk
      control measures verbatim — do not paraphrase the source fields.
   b. Render each test case inline with full setup / steps / expected, the
      same way `review-rtm-assessment` does.
   c. Evaluate H1-H5 against the populated fields. Cite specific `req_id`s,
      `test_id`s, and (where relevant) verbatim sequence steps.
   d. Evaluate A1-A5; default to `"none"` when nothing applies. Be specific —
      vague suggestions are not useful.
   e. Compute the per-hazard verdict per the rules above.
4. Emit the completed report in one message. No preamble, no trailing summary.

## Out of scope

- Modifying the pipeline schema, prompts, or LangGraph nodes. The
  `autoqa/components/hazard_risk_reviewer/` package is the natural future home
  for an LLM-driven hazard pipeline node, but this skill remains a pure
  reformatter regardless.
- Running the LLM pipeline. The user is expected to have a populated
  `HazardPackage` on hand; this skill does not generate or enrich one.
- Writing files. The skill emits markdown to the conversation only.
- JSON output. Use `review-rtm-assessment` for requirement-level coverage and
  this skill for hazard-level mitigation; both emit reviewer-ready markdown.
