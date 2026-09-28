"""仅保留业务拒绝和服务未就绪；SDK、文件系统和数据校验使用原生异常。"""
from collections.abc import Mapping
from typing import Any

from http import HTTPStatus

HTTP_MESSAGES = {
    HTTPStatus.OK: "请求成功",
    HTTPStatus.CREATED: "创建成功",
    HTTPStatus.BAD_REQUEST: "请求参数不合法",
    HTTPStatus.UNAUTHORIZED: "请先完成认证",
    HTTPStatus.FORBIDDEN: "没有权限执行该操作",
    HTTPStatus.NOT_FOUND: "资源不存在",
    HTTPStatus.METHOD_NOT_ALLOWED: "请求方法不支持",
    HTTPStatus.CONFLICT: "资源状态冲突",
    HTTPStatus.REQUEST_ENTITY_TOO_LARGE: "上传文件过大",
    HTTPStatus.UNSUPPORTED_MEDIA_TYPE: "文件格式不支持",
    HTTPStatus.TOO_MANY_REQUESTS: "请求过于频繁，请稍后再试",
    HTTPStatus.INTERNAL_SERVER_ERROR: "服务器内部错误，请稍后重试",
    HTTPStatus.BAD_GATEWAY: "网关响应异常",
    HTTPStatus.SERVICE_UNAVAILABLE: "服务暂时不可用，请稍后重试",
    HTTPStatus.GATEWAY_TIMEOUT: "网关响应超时",
}


def message_for_http_status(status_code: int) -> str:
    if status_code in HTTP_MESSAGES:
        return HTTP_MESSAGES[status_code]
    if 400 <= status_code < 500:
        return "请求无法处理"
    if 500 <= status_code < 600:
        return HTTP_MESSAGES[HTTPStatus.INTERNAL_SERVER_ERROR]
    return "请求已处理"


class AppError(Exception):
    def __init__(self, status_code: int, *, message: str | None = None, context: Mapping[str, Any] | None = None) -> None:
        self.status_code = int(status_code)
        self.message = message or message_for_http_status(status_code)
        self.context = dict(context or {})
        super().__init__(self.message)


class ServiceUnavailableError(AppError):
    """未就绪资源的 503 快捷异常，复用 AppError 处理器。"""

    def __init__(self, detail: str) -> None:
        super().__init__(HTTPStatus.SERVICE_UNAVAILABLE, context={"reason": detail})
