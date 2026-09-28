from __future__ import annotations

from typing import Generic, TypeVar

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from http import HTTPStatus
from app.backend.core.exceptions import message_for_http_status
from app.backend.middleware.request_context import get_current_request_id


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    code: int
    message: str
    data: T | None = None
    request_id: str


class PaginationData(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    has_prev: bool
    has_next: bool


class PageData(BaseModel, Generic[T]):
    items: list[T]
    pagination: PaginationData


def request_id_from_request(request: Request | None = None) -> str:
    if request is not None:
        request_id = getattr(request.state, "request_id", None)
        if isinstance(request_id, str) and request_id:
            return request_id
    return get_current_request_id()


def build_response(*, code: int | HTTPStatus, data: T | None, request_id: str, message: str | None = None,) -> ApiResponse[T]:
    return ApiResponse[T](
        code=int(code),
        message=message or message_for_http_status(code),
        data=data,
        request_id=request_id,
    )


def ok(*, data: T | None = None, request: Request | None = None, request_id: str | None = None, message: str | None = None) -> ApiResponse[T]:
    return build_response(
        code=HTTPStatus.OK,
        message=message,
        data=data,
        request_id=request_id or request_id_from_request(request),
    )


def created(*, data: T | None = None, request: Request | None = None, request_id: str | None = None, message: str | None = None) -> ApiResponse[T]:
    return build_response(
        code=HTTPStatus.CREATED,
        message=message,
        data=data,
        request_id=request_id or request_id_from_request(request),
    )


def fail(*, code: int | HTTPStatus, request: Request | None = None, request_id: str | None = None, message: str | None = None) -> ApiResponse[None]:
    return build_response(
        code=code,
        message=message,
        data=None, 
        request_id=request_id or request_id_from_request(request),
    )


def page_data(*, items: list[T], page: int, page_size: int, total: int) -> PageData[T]:
    total_pages = (total + page_size - 1) // page_size if total else 0
    return PageData[T](
        items=items,
        pagination=PaginationData(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            has_prev=page > 1,
            has_next=page < total_pages,
        ),
    )
