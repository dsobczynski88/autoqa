from langgraph.checkpoint.memory import MemorySaver
from autoqa.components.clients import RateLimitOpenAIClient
from autoqa.components.rtm_review_agent_medtech.pipeline import RTMReviewerRunnable
from autoqa.api.schemas import ReviewRequest, ReviewResponse


class RTMReviewService:
    """
    Wraps the compiled LangGraph pipeline for use by the FastAPI layer.
    Instantiated once at application startup and stored on app.state.
    """

    def __init__(self, client: RateLimitOpenAIClient, model: str):
        checkpointer = MemorySaver()
        self.graph = RTMReviewerRunnable.build_simple_graph(
            client, model, checkpointer=checkpointer
        )

    async def run(self, request: ReviewRequest) -> ReviewResponse:
        config = {"configurable": {"thread_id": request.thread_id}}
        graph_input = {
            "requirement": request.requirement,
            "test_cases": request.test_cases,
        }
        final_state = await self.graph.ainvoke(graph_input, config)
        return ReviewResponse(
            status="completed",
            thread_id=request.thread_id,
            coverage_analysis=final_state.get("coverage_analysis", []),
            decomposed_requirement=final_state.get("decomposed_requirement"),
            test_suite=final_state.get("test_suite"),
        )
