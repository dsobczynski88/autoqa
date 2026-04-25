"""Single-test-case reviewer component."""

from .core import (
    DecomposedRequirement,
    DecomposedSpec,
    EvaluatedReviewObjective,
    Requirement,
    ReviewObjective,
    SpecAnalysis,
    TCReviewState,
    TestCase,
    TestCaseAssessment,
    Verdict,
)
from .nodes import (
    AggregatorNode,
    SingleSpecCoverageNode,
    SingleSpecLogicalNode,
    SingleSpecPrereqsNode,
    TCDecomposerNode,
    dispatch_coverage,
    dispatch_logical,
    dispatch_prereqs,
    load_default_review_objectives,
    make_aggregator_node,
    make_coverage_single_node,
    make_logical_single_node,
    make_prereqs_single_node,
    make_tc_decomposer_node,
)
from .pipeline import TCReviewerRunnable

__all__ = [
    # core models
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
    # nodes
    "TCDecomposerNode",
    "SingleSpecCoverageNode",
    "SingleSpecLogicalNode",
    "SingleSpecPrereqsNode",
    "AggregatorNode",
    # factories
    "make_tc_decomposer_node",
    "make_coverage_single_node",
    "make_logical_single_node",
    "make_prereqs_single_node",
    "make_aggregator_node",
    # dispatchers
    "dispatch_coverage",
    "dispatch_logical",
    "dispatch_prereqs",
    # helpers
    "load_default_review_objectives",
    # runnable
    "TCReviewerRunnable",
]
