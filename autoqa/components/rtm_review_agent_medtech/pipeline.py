import asyncio
from typing import List, Optional, Dict, Any
from langchain_core.runnables import Runnable
from langgraph.graph import StateGraph, START, END
from autoqa.prj_logger import ProjectLogger
from autoqa.components.processors import df_to_prompt_items
from autoqa.components.clients import RateLimitOpenAIClient
from .core import RTMReviewState
from .nodes import (
    make_coverage_evaluator,
    make_decomposer_node,
    make_summarizer_node,
    make_generator_node,
    #make_aggregator_node,
)


class RTMReviewerRunnable:
    """
    LangGraph-based RTM reviewer using OpenAI and Anthropic LLMs.

    Evaluates requirement verification coverage against 4 criteria:
    1. Functional
    2. Input/Output
    3. Boundary
    4. Negative Testing
    
    Initially, a requirement and all traced test cases is supplied. The requirement
    is decomposed to testable blocks using the decomposer node. The test cases are summarized
    via the summary node to focus on what is achieved rather than provide the full raw steps. 
    The intent is to get an overall view of what the test case expects to accomplish and how it intends to 
    do so.

    The decomposed requirement and summarized test cases are assembled using the assemble node. This
    node doesn't require an LLM it is simply an organization step to collect the generated inputs.

    The assembled context is then passed (in parallel) to each of the four (4) evaluator nodes. Each
    evaluator node will update the state with an assessment based on its domain expertise. 

    The assessments across the coverage evaluators is then aggregated at the aggregator node. The intent
    of the aggregator node is to reason using the initial inputs and the assessments 
    from the coverage evaluators to provide a refined, actionable recommendation on any additional steps
    needed to update the test suite. 
    """

    def __init__(self, client: RateLimitOpenAIClient, model: str):

        self.client = client
        self.model = model
        self.graph = RTMReviewerRunnable.build_simple_graph(self.client, self.model)


    @staticmethod
    def build_simple_graph(client: RateLimitOpenAIClient, model: str, checkpointer=None) -> Runnable:
        """
        Build a simple decomposer + summarizer -> coverage evaluator graph.

        Graph structure:
            START
              ↓
            ┌─────────────────────────────────┐
            │DECOMPOSER, SUMMARIZER (parallel)│
            └─────────────────────────────────┘
              ↓ (fan-in: waits for both)
            ┌─────────────────────────────────┐
            │COVERAGE EVALUATOR               │
            │  in:  decomposed_requirement    │
            │       test_suite                │
            └─────────────────────────────────┘
              ↓
            END
        """
        sg = StateGraph(RTMReviewState)

        decomposer = make_decomposer_node(client, model)
        summarizer = make_summarizer_node(client, model)
        generator = make_generator_node(client, model)
        coverage = make_coverage_evaluator(client, model)

        sg.add_node("decomposer", decomposer)
        sg.add_node("summarizer", summarizer)
        sg.add_node("coverage", coverage)

        # Decomposer and summarizer run in parallel from START
        sg.add_edge(START, "decomposer")
        sg.add_edge(START, "summarizer")

        # Generator fans-in from both; receives decomposed_requirement + test_suite via state
        sg.add_edge("decomposer", "coverage")
        sg.add_edge("summarizer", "coverage")

        sg.add_edge("coverage", END)

        flow = sg.compile(checkpointer=checkpointer)
        return flow