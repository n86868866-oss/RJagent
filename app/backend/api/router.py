from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.backend.api.dependencies import get_settings
from app.backend.api.routes import chat, health, papers, preferences
from app.backend.config import Settings
from app.backend.core.responses import ApiResponse, ok

root_router = APIRouter()
business_router = APIRouter(prefix="/api")


@root_router.get("/", response_model=ApiResponse[dict[str, str]], tags=["system"])
async def root(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> ApiResponse[dict[str, str]]:
    return ok(
        data={
            "name": settings.app_name,
            "version": settings.app_version,
            "status": "running",
            "health": "/health/ready",
        },
        request=request,
        message="服务运行中",
    )


@business_router.get("", response_model=ApiResponse[dict[str, str]], tags=["system"])
async def api_index(request: Request) -> ApiResponse[dict[str, str]]:
    return ok(
        data={
            "status": "ok",
            "message": "Business API router is registered.",
        },
        request=request,
        message="API 已注册",
    )

business_router.include_router(papers.router)
business_router.include_router(chat.router)
business_router.include_router(preferences.router)

root_router.include_router(health.router)
root_router.include_router(business_router)
