from __future__ import annotations

import logging
from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.backend.middleware.request_context import get_current_request_id


logger = logging.getLogger("app.backend.access")


class AccessLogMiddleware:
    """Emit start and finish access logs for every HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = getattr(getattr(scope.get("app"), "state", None), "settings", None)
        if not bool(getattr(settings, "log_access_enabled", True)):
            await self.app(scope, receive, send)
            return

        started_at = perf_counter()
        status_code = 500
        self._log_started(scope)

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        except Exception:
            self._log_finished(scope, status_code=500, started_at=started_at)
            raise
        else:
            self._log_finished(scope, status_code=status_code, started_at=started_at)

    def _log_started(self, scope: Scope) -> None:
        logger.info(
            "request_started method=%s path=%s request_id=%s",
            scope.get("method", "-"),
            scope.get("path", "-"),
            get_current_request_id(),
        )

    def _log_finished(self, scope: Scope, *, status_code: int, started_at: float) -> None:
        route = getattr(scope.get("route"), "path", None) or "-"
        logger.info(
            "request_finished method=%s path=%s route=%s status_code=%s duration_ms=%.2f request_id=%s",
            scope.get("method", "-"),
            scope.get("path", "-"),
            route,
            status_code,
            (perf_counter() - started_at) * 1000,
            get_current_request_id(),
        )
