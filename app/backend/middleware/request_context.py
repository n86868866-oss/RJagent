from __future__ import annotations

import contextvars
import re
from uuid import uuid4

from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def generate_request_id() -> str:
    return uuid4().hex


def is_valid_request_id(value: str) -> bool:
    return bool(_REQUEST_ID_PATTERN.fullmatch(value))


def get_current_request_id() -> str:
    return _request_id_var.get()


async def request_context_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Assign one request_id for the whole HTTP request lifecycle."""

    request_id = resolve_request_id(request)
    request.state.request_id = request_id
    token = _request_id_var.set(request_id)

    try:
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    finally:
        _request_id_var.reset(token)


def resolve_request_id(request: Request) -> str:
    settings = getattr(request.app.state, "settings", None)
    trust_inbound = bool(getattr(settings, "trust_inbound_request_id", False))
    if not trust_inbound:
        return generate_request_id()

    inbound = request.headers.get(REQUEST_ID_HEADER)
    if inbound and is_valid_request_id(inbound):
        return inbound
    return generate_request_id()
