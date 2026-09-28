from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from app.backend.api.dependencies import get_health_service, get_settings
from app.backend.services.health.models import HealthCheckResult, LivenessData, ReadinessData
from app.backend.config import Settings
from http import HTTPStatus
from fastapi import HTTPException
from app.backend.core.responses import ApiResponse, build_response, ok, request_id_from_request
from app.backend.services.health.health_service import HealthService


router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=ApiResponse[LivenessData])
async def live(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> ApiResponse[LivenessData]:
    """Check only whether the FastAPI process can answer a request."""

    return ok(
        data=LivenessData(
            status="ok",
            name=settings.app_name,
            version=settings.app_version,
        ),
        request=request,
        message="服务正常",
    )


@router.get("/ready", response_model=ApiResponse[ReadinessData])
async def ready(
    request: Request,
    response: Response,
    service: HealthService = Depends(get_health_service),
) -> ApiResponse[ReadinessData]:
    """Probe required components only; optional components remain unchecked."""

    result = await service.check(include_optional=False)
    data = ReadinessData.model_validate(result)
    if result.status == "not_ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return build_response(
            code=HTTPStatus.SERVICE_UNAVAILABLE,
            data=data,
            message="服务未就绪",
            request_id=request_id_from_request(request),
        )
    return ok(data=data, request=request, message="服务已就绪")


@router.get("/details", response_model=ApiResponse[HealthCheckResult])
async def details(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    service: HealthService = Depends(get_health_service),
) -> ApiResponse[HealthCheckResult]:
    """Run a fresh full check and expose restricted diagnostic fields."""

    if not settings.health_details_enabled:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND)

    result = await service.check()
    data = result
    if result.status == "not_ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return build_response(
            code=HTTPStatus.SERVICE_UNAVAILABLE,
            data=data,
            message="服务未就绪",
            request_id=request_id_from_request(request),
        )
    return ok(data=data, request=request, message="健康详情获取成功")
