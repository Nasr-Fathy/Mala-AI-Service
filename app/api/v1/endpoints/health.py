from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_llm_client
from app.core.config import Settings, get_settings
from app.schemas.common import HealthResponse, ReadinessResponse
from app.services.llm.base import BaseLLMClient

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(llm: BaseLLMClient = Depends(get_llm_client)) -> ReadinessResponse:
    result = await llm.health_check()
    return ReadinessResponse(
        status=result.get("status", "unknown"),
        llm_status=result.get("status", "unknown"),
        model=result.get("model", ""),
        details=result,
    )
