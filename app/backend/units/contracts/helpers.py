from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.backend.api.dependencies import get_health_service, get_settings
from app.backend.api.routes import health
from app.backend.core.exception_handlers import register_exception_handlers
from app.backend.core.exceptions import DuplicatePaperError, PaperFormatUnsupportedError, PermissionDeniedError
from app.backend.core.responses import ApiResponse, created, ok
from app.backend.middleware.access_log import access_log_middleware
from app.backend.middleware.request_context import REQUEST_ID_HEADER, request_context_middleware
from app.backend.services.health_service import ComponentCheckResult, HealthCheckResult


API_RESPONSE_FIELDS = {"code", "message", "data", "request_id"}


class FakeHealthService:
    async def check(self) -> HealthCheckResult:
        return HealthCheckResult(
            status="not_ready",
            checked_at=datetime(2026, 8, 12, 8, 0, 0, tzinfo=timezone.utc),
            components={
                "application": ComponentCheckResult(
                    status="ok",
                    required=True,
                    probe="lifespan_ready_flag",
                    latency_ms=0.0,
                ),
                "text_embedding": ComponentCheckResult(
                    status="error",
                    required=True,
                    probe="real_embedding_request",
                    latency_ms=12.34,
                    error_type="ConnectError",
                    error_message="连接失败",
                ),
            },
        )


def make_settings(**overrides: Any) -> SimpleNamespace:
    values = {
        "app_name": "Contract Test App",
        "app_version": "0.0.0",
        "health_details_enabled": True,
        "log_access_enabled": True,
        "trust_inbound_request_id": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def build_contract_app(*, settings: SimpleNamespace | None = None) -> FastAPI:
    settings = settings or make_settings()
    app = FastAPI()
    app.state.settings = settings
    app.state.ready = True

    app.add_middleware(BaseHTTPMiddleware, dispatch=access_log_middleware)
    app.add_middleware(BaseHTTPMiddleware, dispatch=request_context_middleware)
    register_exception_handlers(app)

    @app.get("/contract/success", response_model=ApiResponse[dict[str, str]])
    async def success(request: Request) -> ApiResponse[dict[str, str]]:
        return ok(data={"status": "ok"}, request=request, message="测试成功")

    @app.post("/contract/created", response_model=ApiResponse[dict[str, str]], status_code=201)
    async def create_resource(request: Request) -> ApiResponse[dict[str, str]]:
        return created(data={"id": "paper-1"}, request=request, message="创建成功")

    @app.delete("/contract/no-content", status_code=204)
    async def no_content() -> Response:
        return Response(status_code=204)

    @app.get("/contract/redirect")
    async def redirect() -> RedirectResponse:
        return RedirectResponse("/contract/success", status_code=302)

    @app.get("/contract/validation", response_model=ApiResponse[dict[str, int]])
    async def validation(request: Request, page: int = Query(ge=1)) -> ApiResponse[dict[str, int]]:
        return ok(data={"page": page}, request=request)

    @app.get("/contract/http-error/{status_code}")
    async def http_error(status_code: int) -> None:
        headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
        raise HTTPException(
            status_code=status_code,
            detail="internal framework detail",
            headers=headers,
        )

    @app.get("/contract/duplicate-paper")
    async def duplicate_paper() -> None:
        raise DuplicatePaperError(fingerprint="test-fingerprint")

    @app.get("/contract/unsupported-paper")
    async def unsupported_paper() -> None:
        raise PaperFormatUnsupportedError(filename="note.txt", content_type="text/plain")

    @app.get("/contract/permission-denied")
    async def permission_denied() -> None:
        raise PermissionDeniedError(context={"scope": "contract"})

    @app.get("/contract/unknown-error")
    async def unknown_error() -> None:
        raise RuntimeError("sensitive internal database url")

    app.include_router(health.router)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_health_service] = FakeHealthService
    return app


def assert_api_response(response: Response, *, http_status: int, code: int | None = None, message: str | None = None) -> dict[str, Any]:
    assert response.status_code == http_status
    request_id = response.headers.get(REQUEST_ID_HEADER)
    assert request_id

    body = response.json()
    assert set(body) == API_RESPONSE_FIELDS
    assert body["code"] == (http_status if code is None else code)
    assert body["request_id"] == request_id
    if message is not None:
        assert body["message"] == message
    return body
