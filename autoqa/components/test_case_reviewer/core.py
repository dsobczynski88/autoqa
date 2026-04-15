"""
Core data models for the single-test-case reviewer.

Shared models (Requirement, DecomposedSpec, DecomposedRequirement, TestCase)
live in autoqa.components.shared.core. This module adds test-case-specific
shapes: a single ReviewObjective, a single SpecAnalysis (reused across the
three review axes), the aggregated assessment, and the TCReviewState TypedDict.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, TypedDict, Annotated
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
    "ReviewObjective",
    "SpecAnalysis",
    "RewrittenPrompt",
    "TestCaseAssessment",
    "TCReviewState",
]


class ReviewObjective(BaseModel):
    """
    One entry in the standardized review-objectives checklist.

    `id` and `description` are supplied by the caller (typically loaded from a
    YAML/JSON file); `assessment` is populated by the aggregator after the
    per-axis analyses complete.
    """
    id: str = Field(..., description="Stable identifier, e.g. 'expected_result_support'.")
    description: str = Field(..., description="What this objective evaluates.")
    assessment: str = Field(default="", description="Aggregator's evaluation outcome for this objective.")


class SpecAnalysis(BaseModel):
    """Per-spec verdict emitted by each axis evaluator (coverage / logical / prereqs)."""
    spec_id: str = Field(..., description="The spec_id from the DecomposedSpec.")
    exists: bool = Field(..., description="True if the axis criterion is met even partially.")
    extent: int = Field(..., ge=0, le=5, description="0 = absent/poor, 5 = strong.")
    assessment: str = Field(..., description="Rationale for the verdict.")


class RewrittenPrompt(BaseModel):
    """Output shape for each rewriter node."""
    rewritten_prompt: str = Field(..., description="System instructions tailored to the current test case and decomposed requirements.")


class TestCaseAssessment(BaseModel):
    """Aggregator output: holistic review of one test case."""
    test_case: TestCase
    requirements: List[Requirement]
    decomposed_requirements: List[DecomposedRequirement]
    evaluated_checklist: List[ReviewObjective] = Field(..., description="Populated review-objectives checklist.")


class TCReviewState(TypedDict, total=False):
    test_case: TestCase
    requirements: List[Requirement]
    review_objectives: List[ReviewObjective]
    decomposed_requirements: Optional[List[DecomposedRequirement]]
    rewritten_coverage_prompt: Optional[str]
    rewritten_logical_prompt: Optional[str]
    rewritten_prereqs_prompt: Optional[str]
    coverage_analysis: Annotated[List[SpecAnalysis], operator.add]
    logical_structure_analysis: Annotated[List[SpecAnalysis], operator.add]
    prereqs_analysis: Annotated[List[SpecAnalysis], operator.add]
    aggregated_assessment: Optional[TestCaseAssessment]
