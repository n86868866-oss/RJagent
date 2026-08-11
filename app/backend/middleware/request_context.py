from __future__ import annotations

import contextvars
import re
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send


REQUEST_ID_HEADER = b"x-request-id"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id",
    default="-",
)


def generate_request_id() -> str:
    return uuid4().hex


def is_valid_request_id(value: str) -> bool:
    return bool(_REQUEST_ID_PATTERN.fullmatch(value))


def get_current_request_id() -> str:
    return _request_id_var.get()


class RequestContextMiddleware:
    """Assign one request_id for the whole HTTP request lifecycle."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._resolve_request_id(scope)
        scope.setdefault("state", {})["request_id"] = request_id
        token = _request_id_var.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers = [
                    (name, value)
                    for name, value in headers
                    if name.lower() != REQUEST_ID_HEADER
                ]
                headers.append((REQUEST_ID_HEADER, request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            _request_id_var.reset(token)

    def _resolve_request_id(self, scope: Scope) -> str:
        settings = getattr(getattr(scope.get("app"), "state", None), "settings", None)
        trust_inbound = bool(getattr(settings, "trust_inbound_request_id", False))
        if not trust_inbound:
            return generate_request_id()

        inbound = self._read_inbound_request_id(scope)
        if inbound and is_valid_request_id(inbound):
            return inbound
        return generate_request_id()

    @staticmethod
    def _read_inbound_request_id(scope: Scope) -> str | None:
        headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        for name, value in headers:
            if name.lower() == REQUEST_ID_HEADER:
                try:
                    return value.decode("ascii")
                except UnicodeDecodeError:
                    return None
        return None
