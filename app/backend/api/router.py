from __future__ import annotations

from fastapi import APIRouter, Depends

from app.backend.api.dependencies import get_settings
from app.backend.api.routes import chat, health, papers, preferences
from app.backend.config import Settings

root_router = APIRouter()
business_router = APIRouter(prefix="/api")


@root_router.get("/", tags=["system"])
async def root(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "health": "/health/ready",
    }


@business_router.get("", tags=["system"])
async def api_index() -> dict[str, str]:
    return {
        "status": "ok",
        "message": "Business API router is registered.",
    }

business_router.include_router(papers.router)
business_router.include_router(chat.router)
business_router.include_router(preferences.router)

root_router.include_router(health.router)
root_router.include_router(business_router)
