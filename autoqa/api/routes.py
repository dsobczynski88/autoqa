from fastapi import APIRouter, Depends, HTTPException, Request
from autoqa.api.schemas import ReviewRequest, ReviewResponse
from autoqa.api.services import RTMReviewService

router = APIRouter(prefix="/api/v1", tags=["RTM Review"])


def get_service(request: Request) -> RTMReviewService:
    return request.app.state.service


@router.get("/", tags=["Health"])
async def root():
    """Root endpoint for health check."""
    return {
        "status": "ok",
        "service": "AutoQA RTM Reviewer API",
        "version": "0.1.0"
    }


@router.post("/review", response_model=ReviewResponse)
async def review(
    body: ReviewRequest,
    service: RTMReviewService = Depends(get_service),
) -> ReviewResponse:
    try:
        return await service.run(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
