import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from openai import AsyncOpenAI
from autoqa.api.routes import router
from autoqa.api.services import RTMReviewService
from autoqa.components.clients import RateLimitOpenAIClient
from autoqa.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = AsyncOpenAI(
        base_url=settings.url,
        api_key=settings.openai_api_key,
        max_retries=settings.max_requests_per_minute
    )

    app.state.service = RTMReviewService(client, settings.model)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="AutoQA RTM Reviewer API",
        version="0.1.0",
        lifespan=lifespan,
    )
    
    # Add root endpoint
    @app.get("/", tags=["Health"])
    async def root():
        """Root endpoint for health check."""
        return {
            "status": "ok",
            "service": "AutoQA RTM Reviewer API",
            "version": "0.1.0",
            "docs": "/docs",
            "openapi": "/openapi.json"
        }
    
    app.include_router(router)
    return app


app = create_app()
