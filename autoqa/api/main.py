from contextlib import asynccontextmanager
from fastapi import FastAPI
from autoqa.api.routes import router
from autoqa.api.services import RTMReviewService
from autoqa.components.clients import RateLimitOpenAIClient
from autoqa.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = RateLimitOpenAIClient(
        api_key=settings.openai_api_key,
        max_requests_per_minute=settings.max_requests_per_minute,
        max_tokens_per_minute=settings.max_tokens_per_minute,
    )
    app.state.service = RTMReviewService(client, settings.model)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="AutoQA RTM Reviewer API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
