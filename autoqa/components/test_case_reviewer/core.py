"""
Core data models for the single-test-case reviewer.

Shared models (Requirement, DecomposedSpec, DecomposedRequirement, TestCase)
live in autoqa.components.shared.core. This module adds test-case-specific
shapes:

- ReviewObjective — input row of the review-objectives checklist (id +
  description, loaded from review_objectives.yaml).
- EvaluatedReviewObjective — aggregator-populated row carrying a binary
  Yes/No verdict plus a `partial` flag that drives Yellow rendering in the
  viewer (mirrors test_suite_reviewer's MandatoryFinding).
- SpecAnalysis — per-spec verdict emitted by each axis evaluator.
- TestCaseAssessment — final aggregator output, mirroring
  SynthesizedAssessment with overall_verdict / comments / clarification_questions.
- TCReviewState — the LangGraph TypedDict that threads everything.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Literal, TypedDict, Annotated
import operator

from autoqa.components.shared.core import (
    Requirement,
    DecomposedSpec,
    DecomposedRequirement,
    TestCase,
)

__all__ = [
    "Requirement",
    "DecomposedSpec",
    "DecomposedRequirement",
    "TestCase",
    "Verdict",
    "ReviewObjective",
    "EvaluatedReviewObjective",
    "SpecAnalysis",
    "TestCaseAssessment",
    "TCReviewState",
]


Verdict = Literal["Yes", "No"]


class ReviewObjective(BaseModel):
    """
    Input row of the standardized review-objectives checklist. Loaded from
    review_objectives.yaml and passed into the graph as initial state.
    """
    id: str = Field(..., description="Stable identifier, e.g. 'expected_result_support'.")
    description: str = Field(..., description="What this objective evaluates.")


class EvaluatedReviewObjective(ReviewObjective):
    """
    Aggregator-populated row: same id/description as the input ReviewObjective,
    plus the verdict, partial flag, and assessment rationale.
    """
    verdict: Verdict = Field(
        ...,
        description="Yes if the test case meets this objective, otherwise No.",
    )
    partial: bool = Field(
        default=False,
        description=(
            "True ONLY when verdict='Yes' AND coverage of this objective is "
            "incomplete in some material way (drives Yellow rendering in the "
            "viewer). Always False when verdict is No. Has NO effect on "
            "overall_verdict aggregation — partial-Yes still passes."
        ),
    )
    assessment: str = Field(default="", description="Aggregator's rationale for the verdict.")


class SpecAnalysis(BaseModel):
    """Per-spec verdict emitted by each axis evaluator (coverage / logical / prereqs)."""
    spec_id: str = Field(..., description="The spec_id from the DecomposedSpec.")
    exists: bool = Field(..., description="True if the axis criterion is met for this spec.")
    assessment: str = Field(..., description="Rationale for the verdict.")


class TestCaseAssessment(BaseModel):
    """Aggregator output: holistic review of one test case."""
    test_case: TestCase
    requirements: List[Requirement]
    decomposed_requirements: List[DecomposedRequirement]
    evaluated_checklist: List[EvaluatedReviewObjective] = Field(
        ..., description="Populated review-objectives checklist (one entry per objective)."
    )
    overall_verdict: Verdict = Field(
        ...,
        description=(
            "Yes iff every item in evaluated_checklist has verdict='Yes'. "
            "Any single No flips this to No. Partial-Yes still counts as Yes."
        ),
    )
    comments: str = Field(
        default="",
        description=(
            "Up to 2 sentences clarifying gaps or partial-Yes findings. "
            "Empty when overall_verdict is Yes and no ambiguity remains."
        ),
    )
    clarification_questions: List[str] = Field(
        default_factory=list,
        description=(
            "Targeted, closed-ended questions whose answers expose whether the "
            "identified gaps in `comments` (and any No verdicts) are valid in "
            "context. Empty list ⇒ N/A (no questions needed)."
        ),
    )


class TCReviewState(TypedDict, total=False):
    test_case: TestCase
    requirements: List[Requirement]
    review_objectives: List[ReviewObjective]
    decomposed_requirements: Optional[List[DecomposedRequirement]]
    coverage_analysis: Annotated[List[SpecAnalysis], operator.add]
    logical_structure_analysis: Annotated[List[SpecAnalysis], operator.add]
    prereqs_analysis: Annotated[List[SpecAnalysis], operator.add]
    aggregated_assessment: Optional[TestCaseAssessment]
