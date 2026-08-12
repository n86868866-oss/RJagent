from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.backend.core.codes import CommonCode, message_for_http_status
from app.backend.core.exceptions import AppError
from app.backend.core.responses import ApiResponse, fail
from app.backend.middleware.request_context import REQUEST_ID_HEADER


logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unknown_exception_handler)


def error_json_response(*, status_code: int, response: ApiResponse[None], headers: Mapping[str, str] | None = None) -> JSONResponse:
    response_headers = dict(headers or {})
    response_headers[REQUEST_ID_HEADER] = response.request_id
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json"),
        headers=response_headers,
    )


async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    response = fail(code=CommonCode.BAD_REQUEST, request=request)
    logger.warning(
        "%s %s 请求参数校验失败 返回%s 提示:%s 校验详情:%s",
        request.method,
        request.url.path,
        CommonCode.BAD_REQUEST,
        response.message,
        exc.errors(),
    )
    return error_json_response(
        status_code=CommonCode.BAD_REQUEST,
        response=response,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    status_code = int(exc.status_code)
    response = fail(code=status_code, message=message_for_http_status(status_code), request=request)
    logger.warning(
        "%s %s HTTP异常 返回%s 提示:%s",
        request.method,
        request.url.path,
        status_code,
        response.message,
    )
    return error_json_response(
        status_code=status_code,
        response=response,
        headers=getattr(exc, "headers", None),
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    response = fail(code=exc.code, message=exc.message, request=request)
    logger.log(
        exc.log_level,
        "%s %s 业务异常 返回%s 业务码%s 提示:%s 上下文:%s",
        request.method,
        request.url.path,
        exc.http_status,
        exc.code,
        response.message,
        exc.context,
    )
    return error_json_response(
        status_code=exc.http_status,
        response=response,
    )


async def unknown_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    response = fail(code=CommonCode.INTERNAL_SERVER_ERROR, request=request)
    logger.exception(
        "%s %s 未知系统异常 返回%s 提示:%s",
        request.method,
        request.url.path,
        CommonCode.INTERNAL_SERVER_ERROR,
        response.message,
    )
    return error_json_response(
        status_code=CommonCode.INTERNAL_SERVER_ERROR,
        response=response,
    )
