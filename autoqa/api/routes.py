from fastapi import APIRouter, Depends, HTTPException, Request

from autoqa.api.schemas import (
    HazardReviewRequest,
    HazardReviewResponse,
    ReviewRequest,
    ReviewResponse,
)
from autoqa.api.services import HazardReviewService, RTMReviewService

router = APIRouter(prefix="/api/v1", tags=["AutoQA"])


def get_rtm_service(request: Request) -> RTMReviewService:
    return request.app.state.rtm_service


def get_hazard_service(request: Request) -> HazardReviewService:
    return request.app.state.hazard_service


@router.post("/review", response_model=ReviewResponse, tags=["RTM Review"])
async def review(
    body: ReviewRequest,
    service: RTMReviewService = Depends(get_rtm_service),
) -> ReviewResponse:
    try:
        return await service.run(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/hazard-review", response_model=HazardReviewResponse, tags=["Hazard Review"])
async def hazard_review(
    body: HazardReviewRequest,
    service: HazardReviewService = Depends(get_hazard_service),
) -> HazardReviewResponse:
    try:
        return await service.run(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
