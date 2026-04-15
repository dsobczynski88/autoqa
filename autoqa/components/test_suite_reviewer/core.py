"""
Core data models for RTM review agent (test suite reviewer).

Shared models (Requirement, DecomposedSpec, DecomposedRequirement, TestCase)
live in autoqa.components.shared.core and are re-exported here for
backward compatibility with existing call sites.
"""

from pydantic import BaseModel, Field
import operator
from typing import Optional, List, TypedDict, Annotated

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
    "SummarizedTestCase",
    "TestSuite",
    "EvaluatedSpec",
    "SynthesizedAssessment",
    "RTMReviewState",
]


class SummarizedTestCase(BaseModel):
    test_case_id: str
    objective: str
    verifies: str
    protocol: List[str]
    acceptance_criteria: List[str]
    is_generated: bool = False

class TestSuite(BaseModel):
    requirement: Requirement
    test_cases: List[TestCase]
    summary: List[SummarizedTestCase]

class EvaluatedSpec(BaseModel):
    """Per-spec coverage verdict from an evaluator node."""
    spec_id: str = Field(..., description="The spec_id from the DecomposedSpec")
    covered_exists: bool = Field(..., description="True if coverage exists in at least one test case of input TestSuite (non-AI generated tests) otherwise False")
    covered_extent: int = Field(..., description="Return a score from 0 - 5 indicating the extent of coverage with 0 indicating no coverage and 5 indicating full coverage of the spec")
    covered_by_test_cases: List[str] = Field(..., description="A list of test case IDs from TestSuite['summary'] that effectively cover the test. In the event no test cases are covered, this should return as an empty list.")
    coverage_rationale: str = Field(..., description="Thought process behind the determination of whether the existing test cases within TestSuite cover or fail to cover the described DecomposedSpec")

class SynthesizedAssessment(BaseModel):
    """MoA-synthesized coverage assessment for a requirement."""
    requirement: Requirement
    coverage_assessment: str = Field(..., description="Synthesized coverage view across functional, negative, and boundary/edge perspectives, citing specific test case IDs")
    comments: str = Field(..., description="Gaps, traced-but-uncovered tests, and recommendations")

class RTMReviewState(TypedDict, total=False):
    requirement: Requirement
    test_cases: List[TestCase]
    decomposed_requirement: Optional[DecomposedRequirement]
    test_suite: Optional[TestSuite]
    coverage_analysis: Annotated[List[EvaluatedSpec], operator.add]
    synthesized_assessment: Optional[SynthesizedAssessment]