"""The only HTTP translation boundary for application and native dependency errors."""
import logging
import sqlite3
from collections.abc import Mapping
from http import HTTPStatus

import grpc
import httpx
import openai
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.backend.core.exceptions import AppError, message_for_http_status
from app.backend.core.responses import ApiResponse, fail
from app.backend.middleware.request_context import REQUEST_ID_HEADER

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(AppError, app_error_handler)
    for error_type in (httpx.HTTPError, openai.APIError, sqlite3.Error, OSError, grpc.RpcError, ResponseHandlingException, UnexpectedResponse):
        app.add_exception_handler(error_type, dependency_exception_handler)
    app.add_exception_handler(Exception, unknown_exception_handler)


def error_json_response(*, status_code: int, response: ApiResponse[None], headers: Mapping[str, str] | None = None) -> JSONResponse:
    response_headers = dict(headers or {})
    response_headers[REQUEST_ID_HEADER] = response.request_id
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"), headers=response_headers)


async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning("%s %s 请求参数校验失败: %s", request.method, request.url.path, exc.errors())
    return error_json_response(status_code=HTTPStatus.BAD_REQUEST, response=fail(code=HTTPStatus.BAD_REQUEST, request=request))


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # HTTPException.detail may come from a library; do not expose it blindly.
    response = fail(code=exc.status_code, message=message_for_http_status(exc.status_code), request=request)
    return error_json_response(status_code=exc.status_code, response=response, headers=exc.headers)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.log(
        # 5xx 是服务故障；4xx 通常是预期的请求拒绝，无需错误堆栈。
        logging.ERROR if exc.status_code >= 500 else logging.WARNING,
        "%s %s %s 返回%s 上下文:%s",
        request.method, request.url.path, exc.message, exc.status_code, exc.context,
        exc_info=(type(exc), exc, exc.__traceback__) if exc.status_code >= 500 else None,
    )
    return error_json_response(status_code=exc.status_code, response=fail(code=exc.status_code, message=exc.message, request=request))


def dependency_status_code(exc: Exception) -> HTTPStatus:
    """只将明确的暂时不可用映射为 503，其他内部故障为 500。"""
    cause = exc.source if isinstance(exc, ResponseHandlingException) else exc
    if isinstance(cause, grpc.RpcError):
        unavailable = {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED, grpc.StatusCode.RESOURCE_EXHAUSTED}
        return HTTPStatus.SERVICE_UNAVAILABLE if cause.code() in unavailable else HTTPStatus.INTERNAL_SERVER_ERROR
    if isinstance(cause, (httpx.TransportError, openai.APIConnectionError, ConnectionError, TimeoutError)):
        return HTTPStatus.SERVICE_UNAVAILABLE
    if isinstance(cause, (httpx.HTTPStatusError, openai.APIStatusError, UnexpectedResponse)):
        status = cause.response.status_code if isinstance(cause, httpx.HTTPStatusError) else cause.status_code
        return HTTPStatus.SERVICE_UNAVAILABLE if status in {408, 429, 502, 503, 504} else HTTPStatus.INTERNAL_SERVER_ERROR
    if isinstance(cause, sqlite3.OperationalError) and getattr(cause, "sqlite_errorcode", None) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        return HTTPStatus.SERVICE_UNAVAILABLE
    return HTTPStatus.INTERNAL_SERVER_ERROR


async def dependency_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    status_code = dependency_status_code(exc)
    logger.error("%s %s %s 返回%s", request.method, request.url.path, message_for_http_status(status_code), status_code,
                 exc_info=(type(exc), exc, exc.__traceback__))
    return error_json_response(status_code=status_code, response=fail(code=status_code, request=request))


async def unknown_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("%s %s 内部未知处理异常", request.method, request.url.path, exc_info=(type(exc), exc, exc.__traceback__))
    return error_json_response(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, response=fail(code=HTTPStatus.INTERNAL_SERVER_ERROR, request=request))
