from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.backend.api.dependencies import get_health_service, get_settings
from app.backend.api.schemas.health import HealthDetailsResponse, LivenessResponse, ReadinessResponse
from app.backend.config import Settings
from app.backend.services.health_service import HealthCheckResult, HealthService


router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LivenessResponse)
async def live(settings: Settings = Depends(get_settings)) -> LivenessResponse:
    """Check only whether the FastAPI process can answer a request."""

    return LivenessResponse(
        status="ok",
        name=settings.app_name,
        version=settings.app_version,
    )


@router.get("/ready", response_model=ReadinessResponse)
async def ready(response: Response, service: HealthService = Depends(get_health_service)) -> HealthCheckResult:
    """Run a fresh full check and expose only readiness fields."""

    result = await service.check()
    if result.status == "not_ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@router.get("/details", response_model=HealthDetailsResponse)
async def details(
    response: Response,
    settings: Settings = Depends(get_settings),
    service: HealthService = Depends(get_health_service),
) -> HealthCheckResult:
    """Run a fresh full check and expose restricted diagnostic fields."""

    if not settings.health_details_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not Found",
        )

    result = await service.check()
    if result.status == "not_ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
