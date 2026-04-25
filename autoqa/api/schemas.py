from typing import List, Optional
from pydantic import BaseModel
from autoqa.components.test_suite_reviewer.core import (
    Requirement,
    TestCase,
    EvaluatedSpec,
    DecomposedRequirement,
    TestSuite,
    SynthesizedAssessment,
)
from autoqa.components.hazard_risk_reviewer.core import (
    HazardAssessment,
    HazardRecord,
    RequirementReview,
)


class ReviewRequest(BaseModel):
    thread_id: str
    requirement: Requirement
    test_cases: List[TestCase]


class ReviewResponse(BaseModel):
    status: str
    thread_id: str
    coverage_analysis: List[EvaluatedSpec]
    decomposed_requirement: Optional[DecomposedRequirement] = None
    test_suite: Optional[TestSuite] = None
    synthesized_assessment: Optional[SynthesizedAssessment] = None


class HazardReviewRequest(BaseModel):
    thread_id: str
    hazard: HazardRecord


class HazardReviewResponse(BaseModel):
    status: str
    thread_id: str
    hazard: HazardRecord
    hazard_assessment: Optional[HazardAssessment] = None
    requirement_reviews: List[RequirementReview] = []
