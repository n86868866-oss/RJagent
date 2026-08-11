from __future__ import annotations

from typing import Generic, TypeVar

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from app.backend.core.codes import CommonCode, resolve_code
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


def build_response(*, code: int | CommonCode, data: T | None, request_id: str, message: str | None = None,) -> ApiResponse[T]:
    spec = resolve_code(code)
    return ApiResponse[T](
        code=int(code),
        message=message or spec.message,
        data=data,
        request_id=request_id,
    )


def ok(*, data: T | None = None, request: Request | None = None, request_id: str | None = None, message: str | None = None) -> ApiResponse[T]:
    return build_response(
        code=CommonCode.OK,
        message=message,
        data=data,
        request_id=request_id or request_id_from_request(request),
    )


def created(*, data: T | None = None, request: Request | None = None, request_id: str | None = None, message: str | None = None) -> ApiResponse[T]:
    return build_response(
        code=CommonCode.CREATED,
        message=message,
        data=data,
        request_id=request_id or request_id_from_request(request),
    )


def fail(*, code: int | CommonCode, request: Request | None = None, request_id: str | None = None, message: str | None = None) -> ApiResponse[None]:
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
