"""Generate a 200-record labelled RTM dataset for evaluating the test_suite_reviewer
LangGraph as a binary classifier.

Domain: Continuous Glucose Monitor SaMD (IEC 82304 health software).
Output: tests/fixtures/test-suite-reviewer-200/{inputs,outputs}.jsonl + description.md

Each of 20 CGM archetypes produces 10 records: 5 known-good (parameter variations) and
5 known-bad (one failing each of M1, M2, M3, M4, M5). Total 200 records: 100 good / 100
bad, evenly distributed across rubric dimensions. The output records are deterministic
ground-truth assessments computed from the test-case dimension labels — they represent
what a faithful pipeline run SHOULD emit, not what any specific LLM does emit.

Run: uv run python scripts/generate_rtm_dataset.py
"""

from __future__ import annotations
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from autoqa.components.test_suite_reviewer.core import (
    Requirement,
    TestCase,
    DecomposedSpec,
    DecomposedRequirement,
    TestSuite,
    SummarizedTestCase,
    EvaluatedSpec,
    CoveringTestCase,
    MandatoryFinding,
    SynthesizedAssessment,
)


OUTPUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "test-suite-reviewer-200"
DIMS = ("M1", "M2", "M3", "M4", "M5")


# ---------------------------------------------------------------------------
# Internal types
# ---------------------------------------------------------------------------

@dataclass
class TCSpec:
    """One test case + per-spec dimension labels.

    `covers[spec_idx]` lists which of {functional, negative, boundary} this TC
    exercises for the spec at index `spec_idx` in the parent record's spec list.
    """
    test_id: str
    description: str
    setup: str
    steps: str
    expectedResults: str
    covers: Dict[int, List[str]]


@dataclass
class RecordInput:
    """Internal builder shape — converted to input + output JSON dicts."""
    req_id: str
    req_text: str
    specs: List[Dict[str, str]]  # each: {description, acceptance_criteria, rationale}
    test_cases: List[TCSpec]
    rationale: str
    description: str
    expected_gap: str
    has_validation_surface: bool
    has_threshold: bool
    label: int
    failing_dim: Optional[str]


# ---------------------------------------------------------------------------
# Mutation: produce bad variant from a good record
# ---------------------------------------------------------------------------

def _strip_dim_label(tcs: List[TCSpec], dim: str) -> List[TCSpec]:
    new = []
    for tc in tcs:
        new_covers = {sidx: [d for d in dims if d != dim] for sidx, dims in tc.covers.items()}
        new_covers = {sidx: dims for sidx, dims in new_covers.items() if dims}
        if new_covers:
            new.append(replace(tc, covers=new_covers))
    return new


def _strip_spec(tcs: List[TCSpec], spec_idx: int) -> List[TCSpec]:
    new = []
    for tc in tcs:
        new_covers = {sidx: dims for sidx, dims in tc.covers.items() if sidx != spec_idx}
        if new_covers:
            new.append(replace(tc, covers=new_covers))
    return new


def make_bad_variant(good: RecordInput, failing_dim: str, new_req_id: str) -> RecordInput:
    """Apply a deliberate gap to a good record."""
    if failing_dim == "M1":
        new_tcs = _strip_dim_label(good.test_cases, "functional")
        gap = "functional"
    elif failing_dim == "M2":
        new_tcs = _strip_dim_label(good.test_cases, "negative")
        gap = "negative"
    elif failing_dim == "M3":
        new_tcs = _strip_dim_label(good.test_cases, "boundary")
        gap = "boundary"
    elif failing_dim == "M4":
        last_idx = len(good.specs) - 1
        new_tcs = _strip_spec(good.test_cases, last_idx)
        gap = "coverage"
    elif failing_dim == "M5":
        new_tcs = good.test_cases
        gap = "terminology"
    else:
        raise ValueError(f"unknown failing_dim {failing_dim!r}")
    return replace(
        good,
        req_id=new_req_id,
        test_cases=new_tcs,
        expected_gap=gap,
        label=0,
        failing_dim=failing_dim,
        description=f"{good.description} (deliberate gap: {failing_dim})",
    )


# ---------------------------------------------------------------------------
# Output computation (deterministic M1-M5 rubric)
# ---------------------------------------------------------------------------

def _make_specs(rec: RecordInput) -> List[DecomposedSpec]:
    return [
        DecomposedSpec(
            spec_id=f"{rec.req_id}-{i+1:02d}",
            description=s["description"],
            acceptance_criteria=s["acceptance_criteria"],
            rationale=s["rationale"],
        )
        for i, s in enumerate(rec.specs)
    ]


def _compute_findings(
    rec: RecordInput,
    specs: List[DecomposedSpec],
    coverage_items: List[EvaluatedSpec],
) -> List[MandatoryFinding]:
    """Apply the M1-M5 rubric exactly as synthesizer-v6.jinja2 prescribes."""
    all_covering = [ctc for c in coverage_items for ctc in c.covered_by_test_cases]
    has_func = any("functional" in c.dimensions for c in all_covering)
    has_neg = any("negative" in c.dimensions for c in all_covering)
    has_bnd = any("boundary" in c.dimensions for c in all_covering)
    func_tcs = sorted({c.test_case_id for c in all_covering if "functional" in c.dimensions})
    neg_tcs = sorted({c.test_case_id for c in all_covering if "negative" in c.dimensions})
    bnd_tcs = sorted({c.test_case_id for c in all_covering if "boundary" in c.dimensions})
    uncovered = [c.spec_id for c in coverage_items if not c.covered_exists]

    m1 = "Yes" if has_func else "No"
    if not rec.has_validation_surface:
        m2 = "N-A"
    else:
        m2 = "Yes" if has_neg else "No"
    if not rec.has_threshold:
        m3 = "N-A"
    else:
        m3 = "Yes" if has_bnd else "No"
    m4 = "No" if uncovered else "Yes"
    m5 = "No" if rec.failing_dim == "M5" else "Yes"

    return [
        MandatoryFinding(
            code="M1",
            dimension="Functional",
            verdict=m1,
            partial=False,
            rationale=(
                f"functional path verified by {', '.join(func_tcs)}"
                if has_func
                else "no positive-path test exercises the requirement"
            ),
            cited_test_case_ids=func_tcs if has_func else [],
            uncovered_spec_ids=[],
        ),
        MandatoryFinding(
            code="M2",
            dimension="Negative",
            verdict=m2,
            partial=False,
            rationale=(
                "requirement exposes no validation surface or failure mode"
                if m2 == "N-A"
                else (
                    f"negative path exercised by {', '.join(neg_tcs)}"
                    if has_neg
                    else "validation surface present but no negative-path test exists"
                )
            ),
            cited_test_case_ids=neg_tcs if has_neg else [],
            uncovered_spec_ids=[],
        ),
        MandatoryFinding(
            code="M3",
            dimension="Boundary",
            verdict=m3,
            partial=False,
            rationale=(
                "requirement names no threshold/limit/transition"
                if m3 == "N-A"
                else (
                    f"boundary verified by {', '.join(bnd_tcs)}"
                    if has_bnd
                    else "threshold/limit present but no boundary test exists"
                )
            ),
            cited_test_case_ids=bnd_tcs if has_bnd else [],
            uncovered_spec_ids=[],
        ),
        MandatoryFinding(
            code="M4",
            dimension="Spec Coverage",
            verdict=m4,
            partial=False,
            rationale=(
                "all specs covered" if m4 == "Yes" else f"uncovered spec(s): {', '.join(uncovered)}"
            ),
            cited_test_case_ids=[],
            uncovered_spec_ids=uncovered,
        ),
        MandatoryFinding(
            code="M5",
            dimension="Terminology",
            verdict=m5,
            partial=False,
            rationale=(
                "aligned"
                if m5 == "Yes"
                else "test-case vocabulary diverges from requirement vocabulary in one or more steps"
            ),
            cited_test_case_ids=[],
            uncovered_spec_ids=[],
        ),
    ]


def build_input_dict(rec: RecordInput) -> dict:
    return {
        "requirement": {"req_id": rec.req_id, "text": rec.req_text},
        "test_cases": [
            {
                "test_id": tc.test_id,
                "description": tc.description,
                "setup": tc.setup,
                "steps": tc.steps,
                "expectedResults": tc.expectedResults,
            }
            for tc in rec.test_cases
        ],
        "rationale": rec.rationale,
        "expected_gap": rec.expected_gap,
        "description": rec.description,
    }


def build_output_dict(rec: RecordInput) -> dict:
    requirement = Requirement(req_id=rec.req_id, text=rec.req_text)
    specs = _make_specs(rec)
    decomp = DecomposedRequirement(
        requirement=requirement, decomposed_specifications=specs
    )

    tcs = [
        TestCase(
            test_id=t.test_id,
            description=t.description,
            setup=t.setup,
            steps=t.steps,
            expectedResults=t.expectedResults,
        )
        for t in rec.test_cases
    ]

    summary = [
        SummarizedTestCase(
            test_case_id=t.test_id,
            objective=t.description,
            verifies=", ".join(specs[sidx].spec_id for sidx in t.covers.keys()),
            protocol=[s for s in t.steps.split("\n") if s.strip()],
            acceptance_criteria=[s for s in t.expectedResults.split("\n") if s.strip()],
            is_generated=False,
        )
        for t in rec.test_cases
    ]

    test_suite = TestSuite(requirement=requirement, test_cases=tcs, summary=summary)

    coverage_items = []
    for spec_idx, spec in enumerate(specs):
        covering = [
            CoveringTestCase(
                test_case_id=tc.test_id,
                dimensions=tc.covers[spec_idx],
                rationale=(
                    f"{tc.test_id} verifies "
                    f"{', '.join(tc.covers[spec_idx])} dimension(s) of {spec.spec_id}"
                ),
            )
            for tc in rec.test_cases
            if spec_idx in tc.covers and tc.covers[spec_idx]
        ]
        coverage_items.append(
            EvaluatedSpec(
                spec_id=spec.spec_id,
                covered_exists=bool(covering),
                covered_by_test_cases=covering,
            )
        )

    findings = _compute_findings(rec, specs, coverage_items)
    overall = "Yes" if all(f.verdict in ("Yes", "N-A") for f in findings) else "No"

    synthesized = SynthesizedAssessment(
        requirement=requirement,
        overall_verdict=overall,
        mandatory_findings=findings,
        comments=(
            ""
            if overall == "Yes"
            else f"Identified gap in dimension: {rec.expected_gap}"
        ),
        clarification_questions=[],
    )

    # Validate every output record before write
    SynthesizedAssessment.model_validate(synthesized.model_dump())

    return {
        "requirement": requirement.model_dump(),
        "test_cases": [tc.model_dump() for tc in tcs],
        "decomposed_requirement": decomp.model_dump(),
        "test_suite": test_suite.model_dump(),
        "coverage_analysis": [c.model_dump() for c in coverage_items],
        "synthesized_assessment": synthesized.model_dump(),
        "_label": rec.label,
        "_failing_dim": rec.failing_dim,
    }


# ---------------------------------------------------------------------------
# Archetype expansion
# ---------------------------------------------------------------------------

def expand_archetype(arch: Dict[str, Any], base_idx: int) -> List[RecordInput]:
    """Build 10 records (5 good + 5 bad) from one archetype."""
    records: List[RecordInput] = []
    param_sets: List[Dict[str, Any]] = arch["param_sets"]
    if len(param_sets) != 5:
        raise ValueError(f"archetype {arch['name']!r} must have exactly 5 param_sets")

    # 5 good variants
    for i in range(5):
        req_idx = base_idx + i + 1
        req_id = f"REQ-CGM-{req_idx:03d}"
        good = _build_good(arch, param_sets[i], req_id)
        records.append(good)

    # 5 bad variants — one per failing dimension
    for i, dim in enumerate(DIMS):
        req_idx = base_idx + 5 + i + 1
        req_id = f"REQ-CGM-{req_idx:03d}"
        good_template = _build_good(arch, param_sets[i], req_id)
        bad = make_bad_variant(good_template, dim, req_id)
        records.append(bad)

    return records


def _build_good(arch: Dict[str, Any], params: Dict[str, Any], req_id: str) -> RecordInput:
    req_text = arch["req_text_tpl"].format(**params)
    specs = [
        {
            "description": s["description"].format(**params),
            "acceptance_criteria": s["acceptance_criteria"].format(**params),
            "rationale": s["rationale"].format(**params),
        }
        for s in arch["specs"]
    ]
    tc_id_prefix = req_id.replace("REQ-", "TC-")
    tcs = [
        TCSpec(
            test_id=f"{tc_id_prefix}-{chr(ord('A') + i)}",
            description=tc_def["description"].format(**params),
            setup=tc_def["setup"].format(**params),
            steps=tc_def["steps"].format(**params),
            expectedResults=tc_def["expectedResults"].format(**params),
            covers={k: list(v) for k, v in tc_def["covers"].items()},
        )
        for i, tc_def in enumerate(arch["tcs"])
    ]
    return RecordInput(
        req_id=req_id,
        req_text=req_text,
        specs=specs,
        test_cases=tcs,
        rationale=arch.get(
            "rationale",
            "test suite covers each decomposed spec across functional, negative, and boundary dimensions",
        ),
        description=arch["description"],
        expected_gap="none",
        has_validation_surface=arch.get("has_validation_surface", True),
        has_threshold=arch.get("has_threshold", True),
        label=1,
        failing_dim=None,
    )


# ---------------------------------------------------------------------------
# Archetype library — 20 CGM SaMD archetypes
#
# Each archetype is a dict with:
#   - name: short label
#   - description: one-line summary
#   - req_text_tpl: requirement text with {param} placeholders
#   - specs: list of decomposed-spec specs (description, acceptance_criteria, rationale)
#   - tcs: list of TC blueprints (description, setup, steps, expectedResults, covers)
#   - param_sets: 5 parameter dicts (used to make 5 good variants + ids for bad variants)
#   - has_validation_surface, has_threshold: drives M2/M3 N-A semantics
# ---------------------------------------------------------------------------

ARCHETYPES: List[Dict[str, Any]] = []


def _common_setup(extra: str = "") -> str:
    base = (
        "CGM SaMD v3.2 in QA test mode; user account 'patient_01' with active subscription; "
        "approved sensor (lot SN-2026-A) on phantom arm; mobile app paired via BLE 5.0; "
        "network monitor open"
    )
    return base + (f"; {extra}" if extra else "")


# --- 1. Hypo alert at threshold -------------------------------------------------
ARCHETYPES.append({
    "name": "hypo_alert",
    "description": "Hypoglycemia alert when glucose drops to or below threshold",
    "req_text_tpl": (
        "The CGM SaMD shall alert the user when the glucose reading drops to or below "
        "{threshold} mg/dL within 30 seconds of the breach."
    ),
    "specs": [
        {"description": "Detect glucose at or below {threshold} mg/dL",
         "acceptance_criteria": "Hypo trigger fires when glucose <= {threshold} mg/dL.",
         "rationale": "Defines the threshold-detection behaviour."},
        {"description": "Display hypo alert within 30 seconds of breach",
         "acceptance_criteria": "Hypo alert UI visible within 30s of trigger.",
         "rationale": "Defines the timing constraint."},
        {"description": "Alert remains visible until user acknowledges",
         "acceptance_criteria": "Alert persists in UI until 'Dismiss' tapped.",
         "rationale": "Ensures persistence of the safety signal."},
    ],
    "tcs": [
        {"description": "Verify hypo alert fires when glucose drops to {threshold} mg/dL",
         "setup": _common_setup("glucose simulator broadcasting steady 100 mg/dL"),
         "steps": ("Step: 1. Drive simulator glucose value to {threshold} mg/dL.\n"
                   "Step: 2. Wait 30 seconds.\n"
                   "Step: 3. Inspect mobile-app alert UI and notification log."),
         "expectedResults": ("ExpectedResult: 1. Glucose reading shows {threshold} mg/dL.\n"
                             "ExpectedResult: 2. Hypo alert modal appears within 30 seconds.\n"
                             "ExpectedResult: 3. Notification log records hypo alert with timestamp."),
         "covers": {0: ["functional", "boundary"], 1: ["functional"]}},
        {"description": "Verify NO hypo alert at glucose just above threshold",
         "setup": _common_setup("simulator at {threshold_above} mg/dL"),
         "steps": ("Step: 1. Hold simulator at {threshold_above} mg/dL for 60s.\n"
                   "Step: 2. Inspect mobile-app alert UI."),
         "expectedResults": ("ExpectedResult: 1. Reading shows {threshold_above} mg/dL.\n"
                             "ExpectedResult: 2. No hypo alert displayed."),
         "covers": {0: ["negative", "boundary"]}},
        {"description": "Verify alert persists until user dismisses",
         "setup": "hypo alert active from prior test step",
         "steps": ("Step: 1. Wait 60 seconds without input.\n"
                   "Step: 2. Inspect alert UI.\n"
                   "Step: 3. Tap 'Dismiss'.\n"
                   "Step: 4. Inspect alert UI again."),
         "expectedResults": ("ExpectedResult: 1. Alert remains visible after wait.\n"
                             "ExpectedResult: 2. Alert closes after Dismiss tap.\n"
                             "ExpectedResult: 3. Notification log records acknowledgement timestamp."),
         "covers": {2: ["functional"]}},
    ],
    "param_sets": [
        {"threshold": 70, "threshold_above": 75},
        {"threshold": 65, "threshold_above": 70},
        {"threshold": 60, "threshold_above": 65},
        {"threshold": 75, "threshold_above": 80},
        {"threshold": 55, "threshold_above": 60},
    ],
})

# --- 2. Hyper alert at threshold ------------------------------------------------
ARCHETYPES.append({
    "name": "hyper_alert",
    "description": "Hyperglycemia alert when glucose rises to or above threshold",
    "req_text_tpl": (
        "The CGM SaMD shall alert the user when the glucose reading rises to or above "
        "{threshold} mg/dL within 60 seconds of the breach."
    ),
    "specs": [
        {"description": "Detect glucose at or above {threshold} mg/dL",
         "acceptance_criteria": "Hyper trigger fires when glucose >= {threshold} mg/dL.",
         "rationale": "Threshold detection."},
        {"description": "Display hyper alert within 60 seconds of breach",
         "acceptance_criteria": "Hyper alert UI visible within 60s of trigger.",
         "rationale": "Timing constraint."},
        {"description": "Alert classified as urgent severity",
         "acceptance_criteria": "Alert severity tag = 'Urgent'.",
         "rationale": "Drives caregiver-tier escalation."},
    ],
    "tcs": [
        {"description": "Verify hyper alert fires at {threshold} mg/dL",
         "setup": _common_setup("simulator broadcasting 150 mg/dL baseline"),
         "steps": ("Step: 1. Drive simulator to {threshold} mg/dL.\n"
                   "Step: 2. Wait 60 seconds.\n"
                   "Step: 3. Inspect alert UI and severity tag."),
         "expectedResults": ("ExpectedResult: 1. Reading shows {threshold} mg/dL.\n"
                             "ExpectedResult: 2. Hyper alert appears within 60s.\n"
                             "ExpectedResult: 3. Alert severity tag reads 'Urgent'."),
         "covers": {0: ["functional", "boundary"], 1: ["functional"], 2: ["functional"]}},
        {"description": "Verify NO hyper alert at glucose just below threshold",
         "setup": _common_setup("simulator at {threshold_below} mg/dL"),
         "steps": ("Step: 1. Hold simulator at {threshold_below} mg/dL for 90s.\n"
                   "Step: 2. Inspect alert UI."),
         "expectedResults": ("ExpectedResult: 1. Reading shows {threshold_below} mg/dL.\n"
                             "ExpectedResult: 2. No hyper alert displayed."),
         "covers": {0: ["negative", "boundary"]}},
        {"description": "Verify hyper alert is logged with severity",
         "setup": "hyper alert active",
         "steps": "Step: 1. Inspect notification log.",
         "expectedResults": ("ExpectedResult: 1. Log entry shows hyper alert with severity 'Urgent' "
                             "and timestamp."),
         "covers": {2: ["functional"]}},
    ],
    "param_sets": [
        {"threshold": 250, "threshold_below": 245},
        {"threshold": 240, "threshold_below": 235},
        {"threshold": 220, "threshold_below": 215},
        {"threshold": 260, "threshold_below": 255},
        {"threshold": 200, "threshold_below": 195},
    ],
})

# --- 3. Calibration entry range bound -------------------------------------------
ARCHETYPES.append({
    "name": "calibration_range",
    "description": "Calibration value must be within accepted physiological range",
    "req_text_tpl": (
        "The CGM SaMD shall accept calibration entries only when the entered value is "
        "between {low_bound} and {high_bound} mg/dL inclusive."
    ),
    "specs": [
        {"description": "Accept calibration values within [{low_bound}, {high_bound}] mg/dL",
         "acceptance_criteria": "Save button enabled and value persists when {low_bound} <= value <= {high_bound}.",
         "rationale": "Physiologically plausible range."},
        {"description": "Reject calibration values outside the range with inline error",
         "acceptance_criteria": "Inline error 'Value out of range' shown; Save disabled.",
         "rationale": "Prevents nonsensical calibration."},
        {"description": "Log every calibration attempt with value and timestamp",
         "acceptance_criteria": "Audit log row appended for every Save click.",
         "rationale": "Traceability."},
    ],
    "tcs": [
        {"description": "Verify in-range value {accept_value} is accepted",
         "setup": _common_setup("calibration screen open"),
         "steps": ("Step: 1. Enter '{accept_value}' into Calibration field.\n"
                   "Step: 2. Tap Save.\n"
                   "Step: 3. Inspect inline message and audit log."),
         "expectedResults": ("ExpectedResult: 1. Value accepted with no error.\n"
                             "ExpectedResult: 2. Save succeeds and audit log shows new entry."),
         "covers": {0: ["functional", "boundary"], 2: ["functional"]}},
        {"description": "Verify out-of-range value {reject_value} is rejected",
         "setup": _common_setup("calibration screen open"),
         "steps": ("Step: 1. Enter '{reject_value}' into Calibration field.\n"
                   "Step: 2. Tap Save.\n"
                   "Step: 3. Inspect inline error and audit log."),
         "expectedResults": ("ExpectedResult: 1. Inline error 'Value out of range' appears.\n"
                             "ExpectedResult: 2. Save button disabled.\n"
                             "ExpectedResult: 3. Audit log unchanged."),
         "covers": {1: ["negative", "boundary"]}},
        {"description": "Verify calibration value at lower bound {low_bound} is accepted",
         "setup": _common_setup("calibration screen open"),
         "steps": ("Step: 1. Enter '{low_bound}' into Calibration field.\n"
                   "Step: 2. Tap Save."),
         "expectedResults": ("ExpectedResult: 1. Value accepted.\n"
                             "ExpectedResult: 2. Audit log appended with timestamp."),
         "covers": {0: ["boundary"], 2: ["functional"]}},
    ],
    "param_sets": [
        {"low_bound": 40, "high_bound": 400, "accept_value": 120, "reject_value": 39},
        {"low_bound": 50, "high_bound": 350, "accept_value": 150, "reject_value": 25},
        {"low_bound": 40, "high_bound": 400, "accept_value": 200, "reject_value": 401},
        {"low_bound": 45, "high_bound": 380, "accept_value": 100, "reject_value": 500},
        {"low_bound": 40, "high_bound": 400, "accept_value": 90, "reject_value": 38},
    ],
})

# --- 4. Sensor warm-up lockout --------------------------------------------------
ARCHETYPES.append({
    "name": "sensor_warmup",
    "description": "Sensor warm-up period locks readings",
    "req_text_tpl": (
        "The CGM SaMD shall lock all glucose readings during the first {warmup_min} minutes "
        "after sensor insertion and display 'Warming up...' to the user."
    ),
    "specs": [
        {"description": "Lock readings during {warmup_min}-minute warm-up window",
         "acceptance_criteria": "No glucose value shown for first {warmup_min} minutes.",
         "rationale": "Sensor stabilisation."},
        {"description": "Display 'Warming up...' status during warm-up",
         "acceptance_criteria": "Status banner visible throughout warm-up.",
         "rationale": "User communication."},
        {"description": "Resume normal readings after warm-up elapses",
         "acceptance_criteria": "Glucose value displayed at warm-up + 1 second.",
         "rationale": "Transition to normal operation."},
    ],
    "tcs": [
        {"description": "Verify readings locked during warm-up",
         "setup": _common_setup("sensor freshly inserted at t=0"),
         "steps": ("Step: 1. Insert sensor at t=0.\n"
                   "Step: 2. Inspect glucose-reading area at t=1 minute.\n"
                   "Step: 3. Inspect status banner."),
         "expectedResults": ("ExpectedResult: 1. Glucose reading area shows '--' (locked).\n"
                             "ExpectedResult: 2. Status banner reads 'Warming up...'."),
         "covers": {0: ["functional"], 1: ["functional"]}},
        {"description": "Verify reading resumes immediately after warm-up at t={warmup_min}m+1s",
         "setup": _common_setup("sensor just past warm-up"),
         "steps": ("Step: 1. Wait until t={warmup_min} minutes 1 second.\n"
                   "Step: 2. Inspect glucose-reading area."),
         "expectedResults": ("ExpectedResult: 1. Glucose value displayed (numeric, mg/dL).\n"
                             "ExpectedResult: 2. Status banner cleared."),
         "covers": {2: ["functional", "boundary"]}},
        {"description": "Verify reading is NOT displayed at t={warmup_min}m-1s (boundary)",
         "setup": _common_setup("sensor near end of warm-up"),
         "steps": ("Step: 1. Wait until t={warmup_min} minutes minus 1 second.\n"
                   "Step: 2. Inspect glucose-reading area."),
         "expectedResults": ("ExpectedResult: 1. Glucose reading area still shows '--'.\n"
                             "ExpectedResult: 2. Status banner still reads 'Warming up...'."),
         "covers": {0: ["negative", "boundary"]}},
    ],
    "param_sets": [
        {"warmup_min": 60},
        {"warmup_min": 90},
        {"warmup_min": 120},
        {"warmup_min": 45},
        {"warmup_min": 30},
    ],
})

# --- 5. Battery-low warning -----------------------------------------------------
ARCHETYPES.append({
    "name": "battery_low",
    "description": "Battery-low warning threshold",
    "req_text_tpl": (
        "The CGM transmitter shall display a low-battery warning to the user when battery "
        "level drops to or below {pct} percent."
    ),
    "specs": [
        {"description": "Detect battery <= {pct}%",
         "acceptance_criteria": "Battery monitor reports level when level <= {pct}.",
         "rationale": "Threshold detection."},
        {"description": "Display low-battery warning to user",
         "acceptance_criteria": "Warning toast or persistent banner visible.",
         "rationale": "User communication."},
        {"description": "Continue normal operation (do not block readings)",
         "acceptance_criteria": "Glucose readings continue to update.",
         "rationale": "Avoid spurious lockout while battery still functional."},
    ],
    "tcs": [
        {"description": "Verify warning fires at {pct}% battery",
         "setup": _common_setup("battery simulator at {pct_above}%"),
         "steps": ("Step: 1. Drive battery simulator to {pct}%.\n"
                   "Step: 2. Wait 10 seconds.\n"
                   "Step: 3. Inspect warning UI and glucose-reading area."),
         "expectedResults": ("ExpectedResult: 1. Battery indicator shows {pct}%.\n"
                             "ExpectedResult: 2. Low-battery warning visible.\n"
                             "ExpectedResult: 3. Glucose reading still updating."),
         "covers": {0: ["functional", "boundary"], 1: ["functional"], 2: ["functional"]}},
        {"description": "Verify NO warning at {pct_above}% (just above threshold)",
         "setup": _common_setup("battery at {pct_above}%"),
         "steps": ("Step: 1. Hold battery at {pct_above}%.\n"
                   "Step: 2. Inspect UI."),
         "expectedResults": ("ExpectedResult: 1. No low-battery warning visible.\n"
                             "ExpectedResult: 2. Glucose reading area normal."),
         "covers": {0: ["negative", "boundary"]}},
        {"description": "Verify glucose readings continue while warning displayed",
         "setup": "low-battery warning active",
         "steps": "Step: 1. Inspect glucose-reading area for 60 seconds.",
         "expectedResults": ("ExpectedResult: 1. Glucose reading updates continuously "
                             "(no '--' lockout)."),
         "covers": {2: ["functional"]}},
    ],
    "param_sets": [
        {"pct": 20, "pct_above": 25},
        {"pct": 15, "pct_above": 20},
        {"pct": 10, "pct_above": 15},
        {"pct": 25, "pct_above": 30},
        {"pct": 5, "pct_above": 10},
    ],
})

# --- 6. BLE pairing timeout -----------------------------------------------------
ARCHETYPES.append({
    "name": "ble_pairing",
    "description": "BLE pairing timeout enforcement",
    "req_text_tpl": (
        "The CGM mobile app shall complete BLE pairing with the transmitter within "
        "{timeout_sec} seconds or fail with a timeout error."
    ),
    "specs": [
        {"description": "Establish BLE pairing within {timeout_sec} seconds",
         "acceptance_criteria": "Paired status reached at or before {timeout_sec}s.",
         "rationale": "User-experience SLA."},
        {"description": "Surface 'Pairing timeout' error after {timeout_sec}s",
         "acceptance_criteria": "Error UI shown; pairing aborted.",
         "rationale": "Failure-mode visibility."},
        {"description": "Release the BLE scan handle on timeout",
         "acceptance_criteria": "BLE scan callback unregistered after timeout.",
         "rationale": "Avoid resource leak."},
    ],
    "tcs": [
        {"description": "Verify pairing succeeds within {timeout_sec} seconds",
         "setup": _common_setup("transmitter in pairing mode, RSSI -60 dBm"),
         "steps": ("Step: 1. Tap 'Pair Transmitter' in app.\n"
                   "Step: 2. Wait up to {timeout_sec} seconds.\n"
                   "Step: 3. Inspect connection status."),
         "expectedResults": ("ExpectedResult: 1. Status updates to 'Connected' before "
                             "{timeout_sec}s.\n"
                             "ExpectedResult: 2. Transmitter MAC shown in connection panel."),
         "covers": {0: ["functional", "boundary"]}},
        {"description": "Verify timeout error when transmitter unreachable",
         "setup": _common_setup("transmitter powered off"),
         "steps": ("Step: 1. Tap 'Pair Transmitter' in app.\n"
                   "Step: 2. Wait {timeout_sec_after} seconds.\n"
                   "Step: 3. Inspect error UI and BLE scan handle."),
         "expectedResults": ("ExpectedResult: 1. After {timeout_sec}s, error 'Pairing timeout' "
                             "displayed.\n"
                             "ExpectedResult: 2. BLE scan handle released "
                             "(no active callback in debug log)."),
         "covers": {1: ["negative", "boundary"], 2: ["functional"]}},
        {"description": "Verify retry available after timeout",
         "setup": "timeout error shown",
         "steps": ("Step: 1. Tap 'Retry'.\n"
                   "Step: 2. Inspect status."),
         "expectedResults": ("ExpectedResult: 1. New pairing attempt initiated.\n"
                             "ExpectedResult: 2. Status returns to 'Searching...'."),
         "covers": {2: ["functional"]}},
    ],
    "param_sets": [
        {"timeout_sec": 30, "timeout_sec_after": 35},
        {"timeout_sec": 45, "timeout_sec_after": 50},
        {"timeout_sec": 60, "timeout_sec_after": 65},
        {"timeout_sec": 20, "timeout_sec_after": 25},
        {"timeout_sec": 90, "timeout_sec_after": 95},
    ],
})

# --- 7. Cloud sync interval -----------------------------------------------------
ARCHETYPES.append({
    "name": "cloud_sync",
    "description": "Cloud sync at fixed interval with retry-on-failure",
    "req_text_tpl": (
        "The CGM mobile app shall sync glucose readings to the cloud every {sync_min} minutes "
        "when the device is online, and retry once on transient failure."
    ),
    "specs": [
        {"description": "Trigger cloud sync every {sync_min} minutes when online",
         "acceptance_criteria": "Sync request issued at t=0 + n*{sync_min}m.",
         "rationale": "Periodic sync cadence."},
        {"description": "Retry once on transient (5xx) failure",
         "acceptance_criteria": "Second request issued within 60s of first failure.",
         "rationale": "Recoverable-error handling."},
        {"description": "Skip sync when device is offline",
         "acceptance_criteria": "No sync request issued when network unavailable.",
         "rationale": "Avoids spurious failure cascades."},
    ],
    "tcs": [
        {"description": "Verify sync request fires at exactly {sync_min}-minute interval",
         "setup": _common_setup("cloud endpoint reachable, network monitor recording"),
         "steps": ("Step: 1. Reset session at t=0.\n"
                   "Step: 2. Wait {sync_min} minutes.\n"
                   "Step: 3. Inspect network monitor for outbound POST to /sync."),
         "expectedResults": ("ExpectedResult: 1. POST /sync request observed at t={sync_min}m "
                             "+/- 5s.\n"
                             "ExpectedResult: 2. Response 200 OK."),
         "covers": {0: ["functional", "boundary"]}},
        {"description": "Verify retry on transient 503 failure",
         "setup": _common_setup("cloud endpoint stub returns 503 once then 200"),
         "steps": ("Step: 1. Trigger sync via test hook.\n"
                   "Step: 2. Inspect network monitor for retry."),
         "expectedResults": ("ExpectedResult: 1. First POST returns 503.\n"
                             "ExpectedResult: 2. Retry POST issued within 60s.\n"
                             "ExpectedResult: 3. Second response 200 OK."),
         "covers": {1: ["functional", "negative"]}},
        {"description": "Verify no sync attempted when offline",
         "setup": _common_setup("network disabled (airplane mode)"),
         "steps": ("Step: 1. Wait {sync_min_after} minutes in airplane mode.\n"
                   "Step: 2. Inspect network monitor."),
         "expectedResults": ("ExpectedResult: 1. Zero POST /sync attempts during window.\n"
                             "ExpectedResult: 2. Local sync queue length increases."),
         "covers": {2: ["negative", "boundary"]}},
    ],
    "param_sets": [
        {"sync_min": 5, "sync_min_after": 6},
        {"sync_min": 10, "sync_min_after": 12},
        {"sync_min": 15, "sync_min_after": 18},
        {"sync_min": 30, "sync_min_after": 35},
        {"sync_min": 60, "sync_min_after": 65},
    ],
})

# --- 8. Audit-log retention -----------------------------------------------------
ARCHETYPES.append({
    "name": "audit_retention",
    "description": "Audit-log retention period",
    "req_text_tpl": (
        "The CGM SaMD shall retain audit-log entries (calibration, alert acknowledgement, "
        "user login) for at least {years} years before any purge is permitted."
    ),
    "specs": [
        {"description": "Persist audit log entries for at least {years} years",
         "acceptance_criteria": "Entry timestamped >{years_minus} years ago is still queryable.",
         "rationale": "Regulatory retention."},
        {"description": "Reject any purge command targeting entries < {years} years old",
         "acceptance_criteria": "Purge call returns error when target entry age < {years}y.",
         "rationale": "Tamper-prevention."},
        {"description": "Allow purge of entries older than {years} years on admin request",
         "acceptance_criteria": "Purge succeeds for entries timestamped >{years} years ago.",
         "rationale": "Storage management within policy."},
    ],
    "tcs": [
        {"description": "Verify {years}-year-old entry still queryable",
         "setup": _common_setup("audit DB seeded with entry dated {years_minus} years ago"),
         "steps": ("Step: 1. Issue audit-query API call for entry.\n"
                   "Step: 2. Inspect response payload."),
         "expectedResults": ("ExpectedResult: 1. Response 200 with entry payload.\n"
                             "ExpectedResult: 2. Timestamp matches seeded value."),
         "covers": {0: ["functional", "boundary"]}},
        {"description": "Verify purge rejected for under-retention entry",
         "setup": _common_setup("audit DB has 1-year-old entry"),
         "steps": ("Step: 1. Issue admin purge call for entry.\n"
                   "Step: 2. Inspect response and DB state."),
         "expectedResults": ("ExpectedResult: 1. Response 403 'Retention policy violation'.\n"
                             "ExpectedResult: 2. Entry still present in DB."),
         "covers": {1: ["negative", "boundary"]}},
        {"description": "Verify purge succeeds for over-retention entry",
         "setup": _common_setup("audit DB has entry dated {years_plus} years ago"),
         "steps": ("Step: 1. Issue admin purge call for entry.\n"
                   "Step: 2. Inspect response and DB state."),
         "expectedResults": ("ExpectedResult: 1. Response 200 'Purged'.\n"
                             "ExpectedResult: 2. Entry removed from DB."),
         "covers": {2: ["functional", "boundary"]}},
    ],
    "param_sets": [
        {"years": 7, "years_minus": 6, "years_plus": 8},
        {"years": 5, "years_minus": 4, "years_plus": 6},
        {"years": 10, "years_minus": 9, "years_plus": 11},
        {"years": 6, "years_minus": 5, "years_plus": 7},
        {"years": 8, "years_minus": 7, "years_plus": 9},
    ],
})

# --- 9. Pump linking transmission interval --------------------------------------
ARCHETYPES.append({
    "name": "pump_link",
    "description": "Glucose readings transmitted to paired insulin pump at fixed interval",
    "req_text_tpl": (
        "The CGM SaMD shall transmit glucose readings to the paired insulin pump every "
        "{interval_sec} seconds when both devices are linked."
    ),
    "specs": [
        {"description": "Transmit reading to pump every {interval_sec} seconds",
         "acceptance_criteria": "Pump receives reading at intervals of {interval_sec}s +/- 2s.",
         "rationale": "Closed-loop cadence."},
        {"description": "Pause transmission when pump link is broken",
         "acceptance_criteria": "No reading transmitted while link state = 'disconnected'.",
         "rationale": "Avoid stale data."},
        {"description": "Resume transmission when pump reconnects",
         "acceptance_criteria": "Transmission cadence restarts within 1 interval after reconnect.",
         "rationale": "Continuity of closed-loop dosing."},
    ],
    "tcs": [
        {"description": "Verify reading transmitted every {interval_sec} seconds",
         "setup": _common_setup("paired pump in test bench, BLE link active"),
         "steps": ("Step: 1. Reset pump receive log.\n"
                   "Step: 2. Wait {window_sec} seconds.\n"
                   "Step: 3. Inspect pump receive log."),
         "expectedResults": ("ExpectedResult: 1. Pump receives readings at intervals of "
                             "{interval_sec}s +/- 2s.\n"
                             "ExpectedResult: 2. Reading values match CGM-app values."),
         "covers": {0: ["functional", "boundary"]}},
        {"description": "Verify transmission pauses when pump unlinks",
         "setup": _common_setup("paired pump powered off"),
         "steps": ("Step: 1. Power off pump.\n"
                   "Step: 2. Wait 60 seconds.\n"
                   "Step: 3. Inspect outbound BLE log on phone."),
         "expectedResults": ("ExpectedResult: 1. After link drops, zero outbound transmissions "
                             "to pump address.\n"
                             "ExpectedResult: 2. Link state reported as 'disconnected'."),
         "covers": {1: ["negative", "functional"]}},
        {"description": "Verify transmission resumes after pump reconnect",
         "setup": "pump powered back on after step above",
         "steps": ("Step: 1. Power pump on.\n"
                   "Step: 2. Wait {interval_sec_plus} seconds.\n"
                   "Step: 3. Inspect pump receive log."),
         "expectedResults": ("ExpectedResult: 1. Pump receives at least one reading within "
                             "{interval_sec_plus}s.\n"
                             "ExpectedResult: 2. Cadence resumes at {interval_sec}s."),
         "covers": {2: ["functional", "boundary"]}},
    ],
    "param_sets": [
        {"interval_sec": 60, "window_sec": 300, "interval_sec_plus": 90},
        {"interval_sec": 30, "window_sec": 180, "interval_sec_plus": 60},
        {"interval_sec": 90, "window_sec": 540, "interval_sec_plus": 120},
        {"interval_sec": 120, "window_sec": 600, "interval_sec_plus": 150},
        {"interval_sec": 300, "window_sec": 900, "interval_sec_plus": 360},
    ],
})

# --- 10. Predictive hypo alert lead time ----------------------------------------
ARCHETYPES.append({
    "name": "predictive_hypo",
    "description": "Predictive hypo alert lead time and accuracy threshold",
    "req_text_tpl": (
        "The CGM SaMD shall predict hypoglycemic events {lead_min} minutes in advance with "
        "a sensitivity of at least {sens_pct} percent across all monitored sessions."
    ),
    "specs": [
        {"description": "Predict hypo {lead_min} minutes ahead of breach",
         "acceptance_criteria": "Predictive alert fires {lead_min}m before glucose <= 70 mg/dL.",
         "rationale": "Lead-time SLA."},
        {"description": "Maintain sensitivity >= {sens_pct}% across the test session",
         "acceptance_criteria": "True-positive rate over 1-hour session >= {sens_pct}%.",
         "rationale": "Predictive accuracy."},
        {"description": "Suppress prediction when sensor data quality is poor",
         "acceptance_criteria": "No prediction issued when sensor noise > 10 mg/dL std-dev.",
         "rationale": "Avoid false-alert fatigue."},
    ],
    "tcs": [
        {"description": "Verify predictive alert fires {lead_min} minutes before hypo breach",
         "setup": _common_setup("simulator running pre-recorded hypo event trace"),
         "steps": ("Step: 1. Start trace at t=0.\n"
                   "Step: 2. Note alert timestamps.\n"
                   "Step: 3. Note actual breach timestamp."),
         "expectedResults": ("ExpectedResult: 1. Predictive alert fires {lead_min}m +/- 1m before "
                             "actual breach.\n"
                             "ExpectedResult: 2. Alert tagged 'Predictive'."),
         "covers": {0: ["functional", "boundary"]}},
        {"description": "Verify session sensitivity meets {sens_pct}% threshold",
         "setup": _common_setup("trace with 10 hypo events over 1 hour"),
         "steps": ("Step: 1. Run trace to completion.\n"
                   "Step: 2. Compare predicted vs actual events.\n"
                   "Step: 3. Compute sensitivity."),
         "expectedResults": ("ExpectedResult: 1. Predicted at least {sens_count} of 10 events.\n"
                             "ExpectedResult: 2. Computed sensitivity >= {sens_pct}%."),
         "covers": {1: ["functional", "boundary"]}},
        {"description": "Verify suppression when sensor noise high",
         "setup": _common_setup("simulator injecting high-noise signal (15 mg/dL std-dev)"),
         "steps": ("Step: 1. Start noisy trace.\n"
                   "Step: 2. Note any predictive alerts."),
         "expectedResults": ("ExpectedResult: 1. Zero predictive alerts during noisy window.\n"
                             "ExpectedResult: 2. Status banner reads 'Sensor signal noisy'."),
         "covers": {2: ["negative", "functional"]}},
    ],
    "param_sets": [
        {"lead_min": 20, "sens_pct": 80, "sens_count": 8},
        {"lead_min": 15, "sens_pct": 85, "sens_count": 9},
        {"lead_min": 30, "sens_pct": 75, "sens_count": 8},
        {"lead_min": 25, "sens_pct": 80, "sens_count": 8},
        {"lead_min": 10, "sens_pct": 90, "sens_count": 9},
    ],
})

# --- 11. Caregiver SMS at urgent threshold --------------------------------------
ARCHETYPES.append({
    "name": "caregiver_sms",
    "description": "Caregiver SMS notification at urgent glucose threshold",
    "req_text_tpl": (
        "The CGM SaMD shall send an SMS notification to all enrolled caregivers when the user's "
        "glucose drops to or below {urgent} mg/dL for more than {sustain_min} consecutive minutes."
    ),
    "specs": [
        {"description": "Detect sustained glucose <= {urgent} mg/dL for > {sustain_min} minutes",
         "acceptance_criteria": "Trigger fires after sustained breach.",
         "rationale": "Confirms persistent severity."},
        {"description": "Deliver SMS to every enrolled caregiver phone",
         "acceptance_criteria": "Each enrolled phone receives SMS within 60s of trigger.",
         "rationale": "Multi-recipient delivery."},
        {"description": "Log SMS delivery status (delivered/failed) per caregiver",
         "acceptance_criteria": "Delivery log row appended for each caregiver.",
         "rationale": "Operational traceability."},
    ],
    "tcs": [
        {"description": "Verify SMS sent after {sustain_min}+ minutes at {urgent} mg/dL",
         "setup": _common_setup("3 enrolled caregivers, SMS gateway in test mode, simulator at 95 mg/dL"),
         "steps": ("Step: 1. Drive simulator to {urgent} mg/dL.\n"
                   "Step: 2. Hold for {sustain_min_plus} minutes.\n"
                   "Step: 3. Inspect SMS gateway log."),
         "expectedResults": ("ExpectedResult: 1. After {sustain_min}m at {urgent} mg/dL, SMS issued.\n"
                             "ExpectedResult: 2. All 3 enrolled phones receive SMS within 60s.\n"
                             "ExpectedResult: 3. Gateway log shows 3 delivered entries."),
         "covers": {0: ["functional", "boundary"], 1: ["functional"], 2: ["functional"]}},
        {"description": "Verify NO SMS when breach lasts under {sustain_min} minutes",
         "setup": _common_setup("simulator at {urgent} mg/dL"),
         "steps": ("Step: 1. Drive simulator to {urgent} mg/dL.\n"
                   "Step: 2. After {sustain_min_minus} minutes, drive simulator to 100 mg/dL.\n"
                   "Step: 3. Inspect SMS gateway log."),
         "expectedResults": ("ExpectedResult: 1. Zero SMS issued during the brief breach.\n"
                             "ExpectedResult: 2. Gateway log unchanged."),
         "covers": {0: ["negative", "boundary"]}},
        {"description": "Verify delivery-failure log entry recorded",
         "setup": _common_setup("one caregiver phone unreachable (carrier 503)"),
         "steps": ("Step: 1. Trigger urgent SMS path.\n"
                   "Step: 2. Inspect delivery log."),
         "expectedResults": ("ExpectedResult: 1. Two entries 'delivered' and one 'failed' in log.\n"
                             "ExpectedResult: 2. Failed entry includes carrier error code."),
         "covers": {2: ["negative", "functional"]}},
    ],
    "param_sets": [
        {"urgent": 55, "sustain_min": 5, "sustain_min_plus": 6, "sustain_min_minus": 3},
        {"urgent": 60, "sustain_min": 5, "sustain_min_plus": 6, "sustain_min_minus": 3},
        {"urgent": 50, "sustain_min": 10, "sustain_min_plus": 11, "sustain_min_minus": 5},
        {"urgent": 65, "sustain_min": 5, "sustain_min_plus": 6, "sustain_min_minus": 4},
        {"urgent": 70, "sustain_min": 15, "sustain_min_plus": 16, "sustain_min_minus": 10},
    ],
})

# --- 12. Time-in-range computation ----------------------------------------------
ARCHETYPES.append({
    "name": "time_in_range",
    "description": "Time-in-range (70-180 mg/dL) over rolling window",
    "req_text_tpl": (
        "The CGM SaMD shall compute and display the user's time-in-range "
        "(70 to 180 mg/dL inclusive) percentage over the most recent {window_hr}-hour window."
    ),
    "specs": [
        {"description": "Maintain a rolling {window_hr}-hour window of glucose readings",
         "acceptance_criteria": "Window contains last {window_hr}h of readings, FIFO.",
         "rationale": "Window bookkeeping."},
        {"description": "Compute time-in-range percentage from window samples",
         "acceptance_criteria": "TIR% = (count of samples in [70, 180]) / total * 100.",
         "rationale": "Metric definition."},
        {"description": "Display TIR% to one decimal place",
         "acceptance_criteria": "UI value matches computed value to within 0.1%.",
         "rationale": "User-facing display."},
    ],
    "tcs": [
        {"description": "Verify TIR computed correctly for {window_hr}h with mix of in/out range",
         "setup": _common_setup("synthetic trace: 70% samples in [70, 180]"),
         "steps": ("Step: 1. Run trace through full {window_hr}h window.\n"
                   "Step: 2. Inspect TIR display and computed value."),
         "expectedResults": ("ExpectedResult: 1. Display shows '70.0%'.\n"
                             "ExpectedResult: 2. Computed value matches input ratio."),
         "covers": {0: ["functional"], 1: ["functional", "boundary"], 2: ["functional"]}},
        {"description": "Verify boundary samples at 70 and 180 mg/dL counted as in-range",
         "setup": _common_setup("synthetic trace: all samples at exactly 70 or 180 mg/dL"),
         "steps": ("Step: 1. Run trace.\n"
                   "Step: 2. Inspect TIR display."),
         "expectedResults": ("ExpectedResult: 1. Display shows '100.0%'.\n"
                             "ExpectedResult: 2. Boundary samples counted as in-range."),
         "covers": {1: ["boundary"]}},
        {"description": "Verify out-of-range samples (69, 181 mg/dL) excluded",
         "setup": _common_setup("trace: all samples at 69 or 181 mg/dL"),
         "steps": ("Step: 1. Run trace.\n"
                   "Step: 2. Inspect TIR display."),
         "expectedResults": ("ExpectedResult: 1. Display shows '0.0%'.\n"
                             "ExpectedResult: 2. Out-of-range samples excluded."),
         "covers": {1: ["negative", "boundary"]}},
    ],
    "param_sets": [
        {"window_hr": 24},
        {"window_hr": 48},
        {"window_hr": 72},
        {"window_hr": 12},
        {"window_hr": 168},
    ],
})

# --- 13. Sensor expiration lockout ----------------------------------------------
ARCHETYPES.append({
    "name": "sensor_expiry",
    "description": "Block readings after sensor lifetime expires",
    "req_text_tpl": (
        "The CGM SaMD shall block all glucose readings and require sensor replacement once "
        "the sensor lifetime of {days} days has elapsed since insertion."
    ),
    "specs": [
        {"description": "Track sensor age from insertion timestamp",
         "acceptance_criteria": "Age field updates every minute.",
         "rationale": "Lifetime bookkeeping."},
        {"description": "Block readings when age > {days} days",
         "acceptance_criteria": "Readings UI shows 'Replace sensor' beyond {days}d.",
         "rationale": "Hard cutoff."},
        {"description": "Allow readings up to and including the {days}-day mark",
         "acceptance_criteria": "Readings continue at age = {days}d - 1m.",
         "rationale": "Inclusive boundary."},
    ],
    "tcs": [
        {"description": "Verify readings continue at sensor age {days}d - 1 minute",
         "setup": _common_setup("clock-mocked sensor age = {days}d - 1m"),
         "steps": ("Step: 1. Set mock age.\n"
                   "Step: 2. Inspect readings UI."),
         "expectedResults": ("ExpectedResult: 1. Glucose value displayed normally.\n"
                             "ExpectedResult: 2. No replacement banner shown."),
         "covers": {0: ["functional"], 2: ["functional", "boundary"]}},
        {"description": "Verify readings blocked at sensor age {days}d + 1 minute",
         "setup": _common_setup("clock-mocked sensor age = {days}d + 1m"),
         "steps": ("Step: 1. Set mock age.\n"
                   "Step: 2. Inspect readings UI."),
         "expectedResults": ("ExpectedResult: 1. Readings UI shows '--'.\n"
                             "ExpectedResult: 2. 'Replace sensor' banner shown."),
         "covers": {1: ["negative", "boundary"]}},
        {"description": "Verify replacement clears the lockout",
         "setup": "expired sensor in lockout",
         "steps": ("Step: 1. Insert new sensor.\n"
                   "Step: 2. Wait warm-up.\n"
                   "Step: 3. Inspect readings UI."),
         "expectedResults": ("ExpectedResult: 1. Readings resume after warm-up.\n"
                             "ExpectedResult: 2. 'Replace sensor' banner cleared."),
         "covers": {0: ["functional"]}},
    ],
    "param_sets": [
        {"days": 10},
        {"days": 14},
        {"days": 7},
        {"days": 30},
        {"days": 21},
    ],
})

# --- 14. CSV export size limit --------------------------------------------------
ARCHETYPES.append({
    "name": "csv_export",
    "description": "CSV export size limit per file",
    "req_text_tpl": (
        "The CGM mobile app shall export reading history as CSV files of at most {mb} MB each, "
        "splitting the export into multiple files when the total exceeds the limit."
    ),
    "specs": [
        {"description": "Single file <= {mb} MB",
         "acceptance_criteria": "Each emitted CSV file size <= {mb} MB.",
         "rationale": "Size limit per file."},
        {"description": "Split exports into multiple files when total exceeds limit",
         "acceptance_criteria": "Export of N MB produces ceil(N/{mb}) files.",
         "rationale": "Partitioning rule."},
        {"description": "Reject exports requesting larger-than-limit single file via API",
         "acceptance_criteria": "API rejects single-file flag with error.",
         "rationale": "API guardrail."},
    ],
    "tcs": [
        {"description": "Verify export at {mb_minus} MB produces 1 file",
         "setup": _common_setup("history seeded with {mb_minus} MB of CSV data"),
         "steps": ("Step: 1. Tap Export.\n"
                   "Step: 2. Inspect resulting files."),
         "expectedResults": ("ExpectedResult: 1. Exactly 1 file created.\n"
                             "ExpectedResult: 2. File size <= {mb} MB."),
         "covers": {0: ["functional", "boundary"]}},
        {"description": "Verify export at {mb_double} MB produces 2 files",
         "setup": _common_setup("history seeded with {mb_double} MB"),
         "steps": ("Step: 1. Tap Export.\n"
                   "Step: 2. Inspect resulting files."),
         "expectedResults": ("ExpectedResult: 1. Two files created.\n"
                             "ExpectedResult: 2. Each file size <= {mb} MB."),
         "covers": {0: ["boundary"], 1: ["functional", "boundary"]}},
        {"description": "Verify API rejects single-file request when total > limit",
         "setup": _common_setup("history > {mb} MB"),
         "steps": ("Step: 1. Call /export?single=true via API.\n"
                   "Step: 2. Inspect response."),
         "expectedResults": ("ExpectedResult: 1. Response 400 'Single-file size exceeds limit'.\n"
                             "ExpectedResult: 2. No file produced."),
         "covers": {2: ["negative", "functional"]}},
    ],
    "param_sets": [
        {"mb": 10, "mb_minus": 9, "mb_double": 20},
        {"mb": 5, "mb_minus": 4, "mb_double": 10},
        {"mb": 25, "mb_minus": 24, "mb_double": 50},
        {"mb": 50, "mb_minus": 49, "mb_double": 100},
        {"mb": 100, "mb_minus": 99, "mb_double": 200},
    ],
})

# --- 15. Multi-account cap ------------------------------------------------------
ARCHETYPES.append({
    "name": "multi_account",
    "description": "Multi-user account cap per device",
    "req_text_tpl": (
        "The CGM mobile app shall support up to {max_n} distinct user accounts on a single "
        "device installation and reject creation of an additional account beyond the cap."
    ),
    "specs": [
        {"description": "Allow up to {max_n} active accounts",
         "acceptance_criteria": "Account creation succeeds for accounts 1..{max_n}.",
         "rationale": "Capacity limit."},
        {"description": "Reject creation of account #{max_n_plus}",
         "acceptance_criteria": "Creation API returns error when current count = {max_n}.",
         "rationale": "Cap enforcement."},
        {"description": "Allow creation again after deletion brings count below cap",
         "acceptance_criteria": "After deleting any account, creation succeeds.",
         "rationale": "Recovery path."},
    ],
    "tcs": [
        {"description": "Verify {max_n}th account is allowed",
         "setup": _common_setup("device with {max_n_minus} existing accounts"),
         "steps": ("Step: 1. Create new account.\n"
                   "Step: 2. Inspect account list."),
         "expectedResults": ("ExpectedResult: 1. Account creation succeeds.\n"
                             "ExpectedResult: 2. Account list shows {max_n} entries."),
         "covers": {0: ["functional", "boundary"]}},
        {"description": "Verify {max_n_plus}th account is rejected",
         "setup": _common_setup("device with {max_n} existing accounts"),
         "steps": ("Step: 1. Attempt to create new account.\n"
                   "Step: 2. Inspect error UI."),
         "expectedResults": ("ExpectedResult: 1. Error 'Account limit reached' shown.\n"
                             "ExpectedResult: 2. Account list still shows {max_n} entries."),
         "covers": {1: ["negative", "boundary"]}},
        {"description": "Verify deletion permits re-creation",
         "setup": _common_setup("device at cap with {max_n} accounts"),
         "steps": ("Step: 1. Delete one account.\n"
                   "Step: 2. Create new account.\n"
                   "Step: 3. Inspect account list."),
         "expectedResults": ("ExpectedResult: 1. Deletion succeeds.\n"
                             "ExpectedResult: 2. New creation succeeds.\n"
                             "ExpectedResult: 3. List again shows {max_n} entries."),
         "covers": {2: ["functional"]}},
    ],
    "param_sets": [
        {"max_n": 5, "max_n_minus": 4, "max_n_plus": 6},
        {"max_n": 3, "max_n_minus": 2, "max_n_plus": 4},
        {"max_n": 10, "max_n_minus": 9, "max_n_plus": 11},
        {"max_n": 8, "max_n_minus": 7, "max_n_plus": 9},
        {"max_n": 4, "max_n_minus": 3, "max_n_plus": 5},
    ],
})

# --- 16. TLS minimum version ----------------------------------------------------
ARCHETYPES.append({
    "name": "tls_min_version",
    "description": "TLS minimum version enforcement on cloud connections",
    "req_text_tpl": (
        "The CGM SaMD shall establish cloud connections only over TLS 1.{min_minor} or higher "
        "and reject any negotiation that downgrades below this minimum."
    ),
    "specs": [
        {"description": "Successfully connect over TLS 1.{min_minor}",
         "acceptance_criteria": "Cloud handshake succeeds with TLS 1.{min_minor}.",
         "rationale": "Minimum acceptable version."},
        {"description": "Reject negotiation that downgrades below TLS 1.{min_minor}",
         "acceptance_criteria": "Connection aborts with 'Insecure protocol' error.",
         "rationale": "Downgrade prevention."},
        {"description": "Log every TLS handshake attempt with negotiated version",
         "acceptance_criteria": "Handshake log entry recorded for each attempt.",
         "rationale": "Security audit traceability."},
    ],
    "tcs": [
        {"description": "Verify successful connection at TLS 1.{min_minor}",
         "setup": _common_setup("cloud test endpoint accepting TLS 1.{min_minor}"),
         "steps": ("Step: 1. Trigger sync.\n"
                   "Step: 2. Inspect connection log."),
         "expectedResults": ("ExpectedResult: 1. Handshake success with negotiated TLS 1.{min_minor}.\n"
                             "ExpectedResult: 2. Sync request transmitted over secure channel."),
         "covers": {0: ["functional", "boundary"], 2: ["functional"]}},
        {"description": "Verify rejection of TLS 1.{min_minor_below} downgrade",
         "setup": _common_setup("cloud test endpoint forcing TLS 1.{min_minor_below}"),
         "steps": ("Step: 1. Trigger sync.\n"
                   "Step: 2. Inspect connection log and error UI."),
         "expectedResults": ("ExpectedResult: 1. Connection aborts with 'Insecure protocol' error.\n"
                             "ExpectedResult: 2. Log entry records rejected handshake at "
                             "TLS 1.{min_minor_below}."),
         "covers": {1: ["negative", "boundary"], 2: ["functional"]}},
        {"description": "Verify TLS 1.{min_minor_above} succeeds (above-minimum version)",
         "setup": _common_setup("cloud endpoint accepting TLS 1.{min_minor_above}"),
         "steps": ("Step: 1. Trigger sync.\n"
                   "Step: 2. Inspect log."),
         "expectedResults": ("ExpectedResult: 1. Handshake success at TLS 1.{min_minor_above}.\n"
                             "ExpectedResult: 2. Sync transmitted."),
         "covers": {0: ["boundary", "functional"]}},
    ],
    "param_sets": [
        {"min_minor": 2, "min_minor_below": 1, "min_minor_above": 3},
        {"min_minor": 3, "min_minor_below": 2, "min_minor_above": 3},
        {"min_minor": 2, "min_minor_below": 0, "min_minor_above": 3},
        {"min_minor": 2, "min_minor_below": 1, "min_minor_above": 3},
        {"min_minor": 3, "min_minor_below": 2, "min_minor_above": 3},
    ],
})

# --- 17. Firmware update battery gate -------------------------------------------
ARCHETYPES.append({
    "name": "firmware_battery_gate",
    "description": "Firmware update permitted only above battery threshold",
    "req_text_tpl": (
        "The CGM transmitter shall accept and apply firmware updates only when the battery "
        "level is at or above {pct} percent at the moment the update is requested."
    ),
    "specs": [
        {"description": "Accept update at battery >= {pct}%",
         "acceptance_criteria": "Update install proceeds when battery >= {pct}.",
         "rationale": "Power-safety guard."},
        {"description": "Reject update at battery < {pct}%",
         "acceptance_criteria": "Update API returns 'Battery insufficient' error.",
         "rationale": "Avoid mid-flash bricking."},
        {"description": "Verify firmware signature before applying",
         "acceptance_criteria": "Update aborts if signature check fails.",
         "rationale": "Tamper prevention."},
    ],
    "tcs": [
        {"description": "Verify update succeeds at {pct}% battery",
         "setup": _common_setup("battery simulator at {pct}%"),
         "steps": ("Step: 1. Push signed firmware via test API.\n"
                   "Step: 2. Inspect update progress and battery log."),
         "expectedResults": ("ExpectedResult: 1. Update accepted and applied.\n"
                             "ExpectedResult: 2. Post-update version matches pushed firmware."),
         "covers": {0: ["functional", "boundary"]}},
        {"description": "Verify update rejected at {pct_below}% battery",
         "setup": _common_setup("battery simulator at {pct_below}%"),
         "steps": ("Step: 1. Push signed firmware via test API.\n"
                   "Step: 2. Inspect response and battery log."),
         "expectedResults": ("ExpectedResult: 1. Response 'Battery insufficient'.\n"
                             "ExpectedResult: 2. Firmware version unchanged."),
         "covers": {1: ["negative", "boundary"]}},
        {"description": "Verify update rejected when signature invalid",
         "setup": _common_setup("battery {pct}%, unsigned firmware payload"),
         "steps": ("Step: 1. Push unsigned firmware.\n"
                   "Step: 2. Inspect response."),
         "expectedResults": ("ExpectedResult: 1. Response 'Signature check failed'.\n"
                             "ExpectedResult: 2. Firmware version unchanged."),
         "covers": {2: ["negative", "functional"]}},
    ],
    "param_sets": [
        {"pct": 50, "pct_below": 45},
        {"pct": 60, "pct_below": 55},
        {"pct": 40, "pct_below": 35},
        {"pct": 70, "pct_below": 65},
        {"pct": 30, "pct_below": 25},
    ],
})

# --- 18. Severe-hypo emergency contact ------------------------------------------
ARCHETYPES.append({
    "name": "severe_emergency",
    "description": "Severe-hypo emergency contact dispatch",
    "req_text_tpl": (
        "The CGM SaMD shall send glucose data and user location to the user's pre-registered "
        "emergency contact when severe hypoglycemia (glucose <= {severe} mg/dL) is sustained "
        "for more than {sustain_min} consecutive minutes without user acknowledgement."
    ),
    "specs": [
        {"description": "Detect sustained glucose <= {severe} mg/dL for > {sustain_min} minutes",
         "acceptance_criteria": "Trigger fires after {sustain_min}m breach.",
         "rationale": "Confirms severity and persistence."},
        {"description": "Suppress trigger if user acknowledges within {sustain_min} minutes",
         "acceptance_criteria": "No emergency call when user taps 'I'm safe' before window elapses.",
         "rationale": "Avoid false dispatch."},
        {"description": "Dispatch payload (glucose history, GPS coords, contact name) to emergency endpoint",
         "acceptance_criteria": "POST to emergency endpoint contains all three fields.",
         "rationale": "Actionable contact data."},
    ],
    "tcs": [
        {"description": "Verify dispatch after {sustain_min}+ min at {severe} mg/dL",
         "setup": _common_setup("registered emergency contact, GPS unlocked, simulator at 80 mg/dL"),
         "steps": ("Step: 1. Drive simulator to {severe} mg/dL.\n"
                   "Step: 2. Hold for {sustain_min_plus} minutes without user input.\n"
                   "Step: 3. Inspect emergency endpoint log."),
         "expectedResults": ("ExpectedResult: 1. POST observed at {sustain_min}m+1m mark.\n"
                             "ExpectedResult: 2. Payload contains glucose history, GPS coords, "
                             "contact name."),
         "covers": {0: ["functional", "boundary"], 2: ["functional"]}},
        {"description": "Verify NO dispatch when user taps 'I'm safe' within window",
         "setup": _common_setup("simulator at {severe} mg/dL"),
         "steps": ("Step: 1. Drive simulator to {severe} mg/dL.\n"
                   "Step: 2. After {sustain_min_minus} minutes, tap 'I'm safe'.\n"
                   "Step: 3. Inspect emergency endpoint log."),
         "expectedResults": ("ExpectedResult: 1. Zero POST observed during window.\n"
                             "ExpectedResult: 2. UI banner clears."),
         "covers": {1: ["negative", "boundary"]}},
        {"description": "Verify dispatch payload schema",
         "setup": "dispatch fired in prior step",
         "steps": "Step: 1. Inspect emergency endpoint log payload.",
         "expectedResults": ("ExpectedResult: 1. Payload includes glucose_history (>=20 samples), "
                             "gps_lat, gps_lon, contact_name fields."),
         "covers": {2: ["functional"]}},
    ],
    "param_sets": [
        {"severe": 50, "sustain_min": 5, "sustain_min_plus": 6, "sustain_min_minus": 3},
        {"severe": 45, "sustain_min": 5, "sustain_min_plus": 6, "sustain_min_minus": 4},
        {"severe": 55, "sustain_min": 10, "sustain_min_plus": 11, "sustain_min_minus": 5},
        {"severe": 40, "sustain_min": 3, "sustain_min_plus": 4, "sustain_min_minus": 2},
        {"severe": 50, "sustain_min": 7, "sustain_min_plus": 8, "sustain_min_minus": 4},
    ],
})

# --- 19. Trend arrow rate of change ---------------------------------------------
ARCHETYPES.append({
    "name": "trend_arrow",
    "description": "Trend-arrow display based on glucose rate-of-change",
    "req_text_tpl": (
        "The CGM SaMD shall display a downward trend arrow when glucose decreases at a rate of "
        "{rate} mg/dL per minute or faster, and clear the arrow when the rate falls below "
        "the threshold."
    ),
    "specs": [
        {"description": "Compute rate-of-change over rolling 5-minute window",
         "acceptance_criteria": "Rate field updated every minute from last 5 samples.",
         "rationale": "Smooth trend signal."},
        {"description": "Display downward arrow when rate <= -{rate} mg/dL/min",
         "acceptance_criteria": "Arrow visible when rate <= -{rate}.",
         "rationale": "Trend visualization."},
        {"description": "Clear arrow when rate > -{rate} mg/dL/min",
         "acceptance_criteria": "Arrow removed when rate exits threshold band.",
         "rationale": "Avoid stale arrow."},
    ],
    "tcs": [
        {"description": "Verify arrow appears at rate of -{rate} mg/dL/min",
         "setup": _common_setup("simulator descending at -{rate} mg/dL/min from 150"),
         "steps": ("Step: 1. Run trace for 5 minutes.\n"
                   "Step: 2. Inspect rate field and arrow display."),
         "expectedResults": ("ExpectedResult: 1. Computed rate = -{rate} mg/dL/min.\n"
                             "ExpectedResult: 2. Downward arrow visible."),
         "covers": {0: ["functional"], 1: ["functional", "boundary"]}},
        {"description": "Verify NO arrow at rate of -{rate_below} mg/dL/min",
         "setup": _common_setup("simulator descending at -{rate_below} mg/dL/min"),
         "steps": ("Step: 1. Run trace for 5 minutes.\n"
                   "Step: 2. Inspect arrow display."),
         "expectedResults": ("ExpectedResult: 1. Computed rate = -{rate_below}.\n"
                             "ExpectedResult: 2. No arrow displayed."),
         "covers": {1: ["negative", "boundary"]}},
        {"description": "Verify arrow clears when rate flattens",
         "setup": "downward arrow active from prior step",
         "steps": ("Step: 1. Drive simulator to flat 100 mg/dL trace.\n"
                   "Step: 2. Wait 5 minutes.\n"
                   "Step: 3. Inspect arrow display."),
         "expectedResults": ("ExpectedResult: 1. Computed rate near 0.\n"
                             "ExpectedResult: 2. Arrow cleared."),
         "covers": {2: ["functional"]}},
    ],
    "param_sets": [
        {"rate": 2, "rate_below": 1},
        {"rate": 3, "rate_below": 2},
        {"rate": 1, "rate_below": 0},
        {"rate": 4, "rate_below": 3},
        {"rate": 2, "rate_below": 1},
    ],
})

# --- 20. Pairing-code expiration ------------------------------------------------
ARCHETYPES.append({
    "name": "pairing_code_expiry",
    "description": "Pairing-code expiration window enforcement",
    "req_text_tpl": (
        "The CGM mobile app shall accept a transmitter pairing code only within {expiry_min} "
        "minutes of code generation; expired codes shall be rejected and require regeneration."
    ),
    "specs": [
        {"description": "Accept pairing code within {expiry_min} minutes of generation",
         "acceptance_criteria": "Pairing succeeds with code age <= {expiry_min}m.",
         "rationale": "Time-bounded usage."},
        {"description": "Reject pairing code older than {expiry_min} minutes",
         "acceptance_criteria": "Pairing fails with 'Code expired' error.",
         "rationale": "Prevent stale-code attacks."},
        {"description": "Require regeneration after expiry",
         "acceptance_criteria": "User flow forces 'Generate new code' on expiry.",
         "rationale": "Recovery path."},
    ],
    "tcs": [
        {"description": "Verify pairing succeeds with code age {expiry_min_minus} minutes",
         "setup": _common_setup("freshly generated pairing code, clock-mocked age = {expiry_min_minus}m"),
         "steps": ("Step: 1. Enter code in pairing dialog.\n"
                   "Step: 2. Inspect pairing status."),
         "expectedResults": ("ExpectedResult: 1. Pairing succeeds.\n"
                             "ExpectedResult: 2. Status shows 'Connected'."),
         "covers": {0: ["functional", "boundary"]}},
        {"description": "Verify pairing fails with code age {expiry_min_plus} minutes",
         "setup": _common_setup("clock-mocked code age = {expiry_min_plus}m"),
         "steps": ("Step: 1. Enter code in pairing dialog.\n"
                   "Step: 2. Inspect error UI."),
         "expectedResults": ("ExpectedResult: 1. Error 'Code expired' shown.\n"
                             "ExpectedResult: 2. Pairing status remains 'Not paired'."),
         "covers": {1: ["negative", "boundary"]}},
        {"description": "Verify regeneration flow after expiry",
         "setup": "expired-code error visible from prior step",
         "steps": ("Step: 1. Tap 'Generate new code'.\n"
                   "Step: 2. Use new code.\n"
                   "Step: 3. Inspect status."),
         "expectedResults": ("ExpectedResult: 1. New code generated.\n"
                             "ExpectedResult: 2. Pairing succeeds with new code."),
         "covers": {2: ["functional"]}},
    ],
    "param_sets": [
        {"expiry_min": 10, "expiry_min_minus": 9, "expiry_min_plus": 11},
        {"expiry_min": 15, "expiry_min_minus": 14, "expiry_min_plus": 16},
        {"expiry_min": 5, "expiry_min_minus": 4, "expiry_min_plus": 6},
        {"expiry_min": 30, "expiry_min_minus": 29, "expiry_min_plus": 31},
        {"expiry_min": 20, "expiry_min_minus": 19, "expiry_min_plus": 21},
    ],
})


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if len(ARCHETYPES) != 20:
        raise RuntimeError(f"expected 20 archetypes, got {len(ARCHETYPES)}")

    all_records: List[RecordInput] = []
    for arch_idx, arch in enumerate(ARCHETYPES):
        base_idx = arch_idx * 10
        all_records.extend(expand_archetype(arch, base_idx))

    if len(all_records) != 200:
        raise RuntimeError(f"expected 200 records, got {len(all_records)}")

    # Validate all id uniqueness
    req_ids = [r.req_id for r in all_records]
    if len(set(req_ids)) != len(req_ids):
        raise RuntimeError("duplicate req_id detected")
    tc_ids = [tc.test_id for r in all_records for tc in r.test_cases]
    if len(set(tc_ids)) != len(tc_ids):
        # In bad variants test_ids reuse the good template's prefix — by design
        # bad records carry the SAME test_ids as their template good record at the
        # same param_set position (since req_ids differ, the TC ids are unique
        # only if we re-prefix). Re-prefix uses req_id so this should be unique.
        # Find duplicates for diagnostics.
        from collections import Counter
        c = Counter(tc_ids)
        dups = [(tc, n) for tc, n in c.items() if n > 1]
        raise RuntimeError(f"duplicate test_id detected: {dups[:5]}")

    inputs_path = OUTPUT_DIR / "inputs.jsonl"
    outputs_path = OUTPUT_DIR / "outputs.jsonl"

    label_counts = {0: 0, 1: 0}
    fail_counts = {dim: 0 for dim in DIMS}

    with inputs_path.open("w", encoding="utf-8") as fi, outputs_path.open(
        "w", encoding="utf-8"
    ) as fo:
        for rec in all_records:
            fi.write(json.dumps(build_input_dict(rec), ensure_ascii=False) + "\n")
            out = build_output_dict(rec)
            fo.write(json.dumps(out, ensure_ascii=False) + "\n")
            label_counts[rec.label] += 1
            if rec.failing_dim:
                fail_counts[rec.failing_dim] += 1

            # Sanity: known-bad records must have at least one verdict='No' that
            # corresponds to the declared failing_dim.
            if rec.label == 0:
                findings = out["synthesized_assessment"]["mandatory_findings"]
                no_codes = [f["code"] for f in findings if f["verdict"] == "No"]
                if rec.failing_dim not in no_codes:
                    raise RuntimeError(
                        f"record {rec.req_id}: failing_dim={rec.failing_dim} "
                        f"but findings emit No on {no_codes}"
                    )

    # Generate description.md
    desc_path = OUTPUT_DIR / "description.md"
    desc_path.write_text(_render_description(label_counts, fail_counts), encoding="utf-8")

    # Stdout summary
    print(f"records: {len(all_records)}")
    print(f"  known-good (label=1): {label_counts[1]}")
    print(f"  known-bad  (label=0): {label_counts[0]}")
    print("failure-mode distribution (known-bads):")
    for dim in DIMS:
        print(f"  {dim}: {fail_counts[dim]}")
    print(f"unique req_ids: {len(set(req_ids))}/{len(req_ids)}")
    print(f"unique test_ids: {len(set(tc_ids))}/{len(tc_ids)}")
    print(f"wrote: {inputs_path}")
    print(f"wrote: {outputs_path}")
    print(f"wrote: {desc_path}")


def _render_description(label_counts: Dict[int, int], fail_counts: Dict[str, int]) -> str:
    total = label_counts[0] + label_counts[1]
    return f"""# Synthetic RTM Dataset — CGM SaMD (200 records)

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
- **Known good** (label=1, overall_verdict=Yes): {label_counts[1]} records.
- **Known bad**  (label=0, overall_verdict=No):  {label_counts[0]} records.
- **Total**: {total} records.

## Failure-mode distribution (known bads)
- M1 Functional No: {fail_counts['M1']} records.
- M2 Negative No:   {fail_counts['M2']} records.
- M3 Boundary No:   {fail_counts['M3']} records.
- M4 Spec Coverage No: {fail_counts['M4']} records.
- M5 Terminology No:   {fail_counts['M5']} records.
- (Sum = {sum(fail_counts.values())}; matches known-bad count.)

## Statistical posture (Regime 1 — overall accuracy CI)
- Per-class n = {label_counts[1]} (good) and {label_counts[0]} (bad). Total n = {total}.
- 95% confidence interval on overall accuracy at 50/50 prior:
  margin of error ε ≈ sqrt(0.96 / n_per_class) ≈ ±10.0% (worst case, p = 0.5).
- Per-rubric-cell coverage: ~{fail_counts['M1']} known-bads per failing dimension. With
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
  finding's verdict is in `{{Yes, N-A}}`.

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
"""


if __name__ == "__main__":
    main()
