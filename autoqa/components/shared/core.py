"""
Shared Pydantic models reused across reviewer components
(test_suite_reviewer, test_case_reviewer, hazard_risk_reviewer).
"""

from pydantic import BaseModel
from typing import Optional, List


class Requirement(BaseModel):
    """Software requirement model."""
    req_id: Optional[str] = None
    text: str


class DecomposedSpec(BaseModel):
    spec_id: str
    description: str
    acceptance_criteria: str
    rationale: str


class DecomposedRequirement(BaseModel):
    requirement: Requirement
    decomposed_specifications: List[DecomposedSpec]


class TestCase(BaseModel):
    test_id: str
    description: str
    setup: Optional[str] = None
    steps: Optional[str] = None
    expectedResults: Optional[str] = None