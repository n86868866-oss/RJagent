from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.backend.core.codes import CommonCode, message_for_http_status
from app.backend.core.exceptions import AppError
from app.backend.core.responses import fail


logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unknown_exception_handler)


async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    response = fail(code=CommonCode.BAD_REQUEST, request=request)
    logger.warning(
        "request_validation_error request_id=%s method=%s path=%s errors=%s",
        response.request_id,
        request.method,
        request.url.path,
        exc.errors(),
    )
    return JSONResponse(
        status_code=CommonCode.BAD_REQUEST,
        content=response.model_dump(mode="json"),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    status_code = int(exc.status_code)
    response = fail(
        code=status_code,
        message=message_for_http_status(status_code),
        request=request,
    )
    logger.warning(
        "http_exception request_id=%s method=%s path=%s status_code=%s",
        response.request_id,
        request.method,
        request.url.path,
        status_code,
    )
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json"),
        headers=getattr(exc, "headers", None),
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    response = fail(code=exc.code, message=exc.message, request=request)
    logger.log(
        exc.log_level,
        "app_error request_id=%s method=%s path=%s code=%s http_status=%s context=%s",
        response.request_id,
        request.method,
        request.url.path,
        exc.code,
        exc.http_status,
        exc.context,
    )
    return JSONResponse(
        status_code=exc.http_status,
        content=response.model_dump(mode="json"),
    )


async def unknown_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    response = fail(code=CommonCode.INTERNAL_SERVER_ERROR, request=request)
    logger.exception(
        "unknown_exception request_id=%s method=%s path=%s",
        response.request_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=CommonCode.INTERNAL_SERVER_ERROR,
        content=response.model_dump(mode="json"),
    )
