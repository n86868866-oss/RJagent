from __future__ import annotations

from fastapi import Request

from app.backend.config import Settings
from app.backend.services.health_service import HealthService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_health_service(request: Request) -> HealthService:
    return HealthService(
        app=request.app,
        settings=request.app.state.settings,
    )
