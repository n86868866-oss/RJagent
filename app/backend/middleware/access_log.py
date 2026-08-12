from __future__ import annotations

import logging
from time import perf_counter

from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


logger = logging.getLogger(__name__)


async def access_log_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Emit start and finish access logs for every HTTP request."""

    settings = getattr(request.app.state, "settings", None)
    if not bool(getattr(settings, "log_access_enabled", True)):
        return await call_next(request)

    started_at = perf_counter()
    log_started(request)

    try:
        response = await call_next(request)
    except Exception:
        log_finished(request, status_code=500, started_at=started_at)
        raise
    log_finished(request, status_code=response.status_code, started_at=started_at)
    return response


def log_started(request: Request) -> None:
    logger.info(
        "%s %s 请求开始",
        request.method,
        request.url.path,
    )


def log_finished(request: Request, *, status_code: int, started_at: float) -> None:
    logger.info(
        "%s %s 请求结束 返回%s 耗时%.2fms",
        request.method,
        request.url.path,
        status_code,
        (perf_counter() - started_at) * 1000,
    )
