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
