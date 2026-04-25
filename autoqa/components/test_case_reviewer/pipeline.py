"""
LangGraph pipeline for the single-test-case reviewer.

A TestCase plus its traced Requirements (and a review-objectives checklist)
enter at START. The decomposer splits each requirement into atomic specs.
A no-op coverage_router then fans out three independent waves of Sends —
one per review axis — to per-spec evaluators that run in parallel. The
aggregator synthesizes the three accumulated SpecAnalysis lists into a
single TestCaseAssessment with the review-objectives checklist populated.
"""
from pathlib import Path
from typing import Optional, Union

from langchain_core.runnables import Runnable
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END

from autoqa.components.clients import RateLimitOpenAIClient
from autoqa.core.config import settings
from autoqa.utils import save_graph_png

from .core import TCReviewState
from .nodes import (
    dispatch_coverage,
    dispatch_logical,
    dispatch_prereqs,
    make_aggregator_node,
    make_coverage_single_node,
    make_logical_single_node,
    make_prereqs_single_node,
    make_tc_decomposer_node,
)


class TCReviewerRunnable:
    """
    LangGraph-based single-test-case reviewer.

    Graph structure:
        START
          ↓
        ┌──────────────────────────────────────────┐
        │ DECOMPOSER (sequential loop over reqs)    │
        └──────────────────────────────────────────┘
          ↓
        ┌──────────────────────────────────────────┐
        │ COVERAGE_ROUTER (sync no-op)              │
        └──────────────────────────────────────────┘
          ↓ 3× add_conditional_edges → Send × N each
        ┌─────────────┬─────────────┬─────────────┐
        │ coverage_   │ logical_    │ prereqs_    │
        │ evaluator×N │ evaluator×N │ evaluator×N │
        └─────────────┴─────────────┴─────────────┘
          ↓ (operator.add reducers fan in per axis)
        ┌──────────────────────────────────────────┐
        │ AGGREGATOR  (MoA-like synthesis)          │
        └──────────────────────────────────────────┘
          ↓
        END
    """

    def __init__(
        self,
        client: RateLimitOpenAIClient,
        model: str,
        model_kwargs: dict = {},
        checkpointer: Union[MemorySaver, None] = None,
    ):
        self.client = client
        self.model = model
        self.model_kwargs = model_kwargs
        self.checkpointer = checkpointer
        self.graph = self.build()

    def build(self) -> Runnable:
        sg = StateGraph(TCReviewState)

        decomposer = make_tc_decomposer_node(
            self.client, self.model, self.model_kwargs,
        )
        coverage_eval = make_coverage_single_node(
            self.client, self.model, self.model_kwargs,
        )
        logical_eval = make_logical_single_node(
            self.client, self.model, self.model_kwargs,
        )
        prereqs_eval = make_prereqs_single_node(
            self.client, self.model, self.model_kwargs,
        )
        aggregator = make_aggregator_node(
            self.client, self.model, self.model_kwargs,
        )

        sg.add_node("decomposer", decomposer)
        # Join barrier: add_conditional_edges needs a single named source for
        # each fan-out. coverage_router is the shared parent that all three
        # axis dispatchers branch from.
        sg.add_node("coverage_router", lambda state: {})
        sg.add_node("coverage_evaluator", coverage_eval)
        sg.add_node("logical_evaluator", logical_eval)
        sg.add_node("prereqs_evaluator", prereqs_eval)
        sg.add_node("aggregator", aggregator)

        sg.add_edge(START, "decomposer")
        sg.add_edge("decomposer", "coverage_router")

        sg.add_conditional_edges("coverage_router", dispatch_coverage, ["coverage_evaluator"])
        sg.add_conditional_edges("coverage_router", dispatch_logical, ["logical_evaluator"])
        sg.add_conditional_edges("coverage_router", dispatch_prereqs, ["prereqs_evaluator"])

        sg.add_edge("coverage_evaluator", "aggregator")
        sg.add_edge("logical_evaluator", "aggregator")
        sg.add_edge("prereqs_evaluator", "aggregator")
        sg.add_edge("aggregator", END)

        flow = sg.compile(checkpointer=self.checkpointer)
        save_graph_png(flow, Path(settings.log_file_path).parent / "tc_graph.png")
        return flow
