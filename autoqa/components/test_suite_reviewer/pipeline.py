import asyncio
from pathlib import Path
from typing import List, Optional, Dict, Any, Union
from langchain_core.runnables import Runnable
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from autoqa.core.config import settings, PromptConfig
from autoqa.utils import save_graph_png
from autoqa.prj_logger import ProjectLogger
from autoqa.components.processors import df_to_prompt_items
from autoqa.components.clients import RateLimitOpenAIClient
from .core import RTMReviewState
from .nodes import (
    make_coverage_evaluator,
    make_decomposer_node,
    make_summarizer_node,
    make_generator_node,
    make_synthesizer_node,
    dispatch_coverage,
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

    def __init__(
        self,
        client: RateLimitOpenAIClient,
        model: str,
        model_kwargs: dict = {},
        checkpointer: Union[MemorySaver, None] = None,
        prompt_config: Optional[PromptConfig] = None,
    ):

        self.client = client
        self.model = model
        self.model_kwargs = model_kwargs
        self.checkpointer = checkpointer # currently the graph collects intermediate responses via operator.add (no specific checkpointer implemented)
        self.prompt_config = prompt_config if prompt_config is not None else settings.prompt_config
        self.graph = self.build()


    def build(self) -> Runnable:
        """
        Build the graph to evaluate test case suites.

        Graph structure:
            START
              ↓
            ┌─────────────────────────────────┐
            │DECOMPOSER, SUMMARIZER (parallel)│
            └─────────────────────────────────┘
              ↓ (fan-in: waits for both)
            ┌─────────────────────────────────┐
            │COVERAGE_ROUTER (sync point)     │
            └─────────────────────────────────┘
              ↓ dispatch_coverage → Send × N
            ┌─────────────────────────────────┐
            │SPEC_EVALUATOR × N  (parallel)   │
            └─────────────────────────────────┘
              ↓ (fan-in: operator.add on coverage_analysis)
            ┌─────────────────────────────────┐
            │SYNTHESIZER  MoA-like aggregation│
            └─────────────────────────────────┘
              ↓
            END
        """
        sg = StateGraph(RTMReviewState)

        decomposer = make_decomposer_node(
            self.client, self.model, self.model_kwargs,
            prompt_template=self.prompt_config.decomposer,
        )
        summarizer = make_summarizer_node(
            self.client, self.model, self.model_kwargs,
            prompt_template=self.prompt_config.summarizer,
        )
        spec_evaluator = make_coverage_evaluator(
            self.client, self.model, self.model_kwargs,
            prompt_template=self.prompt_config.coverage,
        )
        synthesizer = make_synthesizer_node(
            self.client, self.model, self.model_kwargs,
            prompt_template=self.prompt_config.synthesizer,
        )

        sg.add_node("decomposer", decomposer)
        sg.add_node("summarizer", summarizer)
        sg.add_node("coverage_router", lambda state: {})
        sg.add_node("spec_evaluator", spec_evaluator)
        sg.add_node("synthesizer", synthesizer)

        # Decomposer and summarizer run in parallel from START
        sg.add_edge(START, "decomposer")
        sg.add_edge(START, "summarizer")

        # Fan-in to coverage_router, then fan-out via Send to N parallel spec evaluators
        sg.add_edge("decomposer", "coverage_router")
        sg.add_edge("summarizer", "coverage_router")
        sg.add_conditional_edges("coverage_router", dispatch_coverage, ["spec_evaluator"])

        # Synthesizer aggregates coverage evaluations (MoA-like pattern)
        # operator.add on coverage_analysis acts as fan-in across all spec_evaluator results
        sg.add_edge("spec_evaluator", "synthesizer")
        sg.add_edge("synthesizer", END)

        flow = sg.compile(checkpointer=self.checkpointer)
        save_graph_png(flow, Path(settings.log_file_path).parent / "graph.png")
        return flow