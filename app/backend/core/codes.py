from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class CommonCode(IntEnum):
    OK = 200
    CREATED = 201
    MOVED_PERMANENTLY = 301
    FOUND = 302
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    METHOD_NOT_ALLOWED = 405
    CONFLICT = 409
    PAYLOAD_TOO_LARGE = 413
    UNSUPPORTED_MEDIA_TYPE = 415
    TOO_MANY_REQUESTS = 429
    INTERNAL_SERVER_ERROR = 500
    BAD_GATEWAY = 502
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504


class BusinessCode(IntEnum):
    PAPER_ALREADY_EXISTS = 41001
    PAPER_FORMAT_UNSUPPORTED = 41002
    SQLITE_UNAVAILABLE = 50102
    QDRANT_UNAVAILABLE = 50103
    TEXT_EMBEDDING_UNAVAILABLE = 50104
    MINERU_UNAVAILABLE = 50105
    MINERU_RESULT_INVALID = 50106
    FILE_STORAGE_UNAVAILABLE = 50107
    LANGCHAIN_UNAVAILABLE = 50108
    TEXT_EMBEDDING_ERROR = 50201


@dataclass(frozen=True, slots=True)
class CodeSpec:
    code: int
    http_status: int
    message: str


CODE_SPECS: dict[int, CodeSpec] = {
    CommonCode.OK: CodeSpec(CommonCode.OK, CommonCode.OK, "请求成功"),
    CommonCode.CREATED: CodeSpec(CommonCode.CREATED, CommonCode.CREATED, "创建成功"),
    CommonCode.MOVED_PERMANENTLY: CodeSpec(CommonCode.MOVED_PERMANENTLY, CommonCode.MOVED_PERMANENTLY, "资源已永久重定向"),
    CommonCode.FOUND: CodeSpec(CommonCode.FOUND, CommonCode.FOUND, "资源已临时重定向"),
    CommonCode.BAD_REQUEST: CodeSpec(CommonCode.BAD_REQUEST, CommonCode.BAD_REQUEST, "请求参数不合法"),
    CommonCode.UNAUTHORIZED: CodeSpec(CommonCode.UNAUTHORIZED, CommonCode.UNAUTHORIZED, "请先完成认证"),
    CommonCode.FORBIDDEN: CodeSpec(CommonCode.FORBIDDEN, CommonCode.FORBIDDEN, "没有权限执行该操作"),
    CommonCode.NOT_FOUND: CodeSpec(CommonCode.NOT_FOUND, CommonCode.NOT_FOUND, "接口不存在"),
    CommonCode.METHOD_NOT_ALLOWED: CodeSpec(CommonCode.METHOD_NOT_ALLOWED, CommonCode.METHOD_NOT_ALLOWED, "请求方法不支持"),
    CommonCode.CONFLICT: CodeSpec(CommonCode.CONFLICT, CommonCode.CONFLICT, "资源状态冲突"),
    CommonCode.PAYLOAD_TOO_LARGE: CodeSpec(CommonCode.PAYLOAD_TOO_LARGE, CommonCode.PAYLOAD_TOO_LARGE, "上传内容过大"),
    CommonCode.UNSUPPORTED_MEDIA_TYPE: CodeSpec(CommonCode.UNSUPPORTED_MEDIA_TYPE, CommonCode.UNSUPPORTED_MEDIA_TYPE, "不支持的内容类型"),
    CommonCode.TOO_MANY_REQUESTS: CodeSpec(CommonCode.TOO_MANY_REQUESTS, CommonCode.TOO_MANY_REQUESTS, "请求过于频繁，请稍后再试"),
    CommonCode.INTERNAL_SERVER_ERROR: CodeSpec(CommonCode.INTERNAL_SERVER_ERROR, CommonCode.INTERNAL_SERVER_ERROR, "服务暂时不可用，请稍后再试"),
    CommonCode.BAD_GATEWAY: CodeSpec(CommonCode.BAD_GATEWAY, CommonCode.BAD_GATEWAY, "依赖服务响应异常"),
    CommonCode.SERVICE_UNAVAILABLE: CodeSpec(CommonCode.SERVICE_UNAVAILABLE, CommonCode.SERVICE_UNAVAILABLE, "依赖服务暂不可用"),
    CommonCode.GATEWAY_TIMEOUT: CodeSpec(CommonCode.GATEWAY_TIMEOUT, CommonCode.GATEWAY_TIMEOUT, "依赖服务响应超时"),
    BusinessCode.PAPER_ALREADY_EXISTS: CodeSpec(BusinessCode.PAPER_ALREADY_EXISTS, CommonCode.CONFLICT, "论文已存在"),
    BusinessCode.PAPER_FORMAT_UNSUPPORTED: CodeSpec(BusinessCode.PAPER_FORMAT_UNSUPPORTED, CommonCode.UNSUPPORTED_MEDIA_TYPE, "文件格式不支持"),
    BusinessCode.SQLITE_UNAVAILABLE: CodeSpec(BusinessCode.SQLITE_UNAVAILABLE, CommonCode.SERVICE_UNAVAILABLE, "SQLite 暂不可用"),
    BusinessCode.QDRANT_UNAVAILABLE: CodeSpec(BusinessCode.QDRANT_UNAVAILABLE, CommonCode.SERVICE_UNAVAILABLE, "向量数据库暂不可用"),
    BusinessCode.TEXT_EMBEDDING_UNAVAILABLE: CodeSpec(BusinessCode.TEXT_EMBEDDING_UNAVAILABLE, CommonCode.SERVICE_UNAVAILABLE, "文本向量服务暂不可用"),
    BusinessCode.MINERU_UNAVAILABLE: CodeSpec(BusinessCode.MINERU_UNAVAILABLE, CommonCode.SERVICE_UNAVAILABLE, "MinerU 服务暂不可用"),
    BusinessCode.MINERU_RESULT_INVALID: CodeSpec(BusinessCode.MINERU_RESULT_INVALID, CommonCode.BAD_GATEWAY, "MinerU 解析结果异常"),
    BusinessCode.FILE_STORAGE_UNAVAILABLE: CodeSpec(BusinessCode.FILE_STORAGE_UNAVAILABLE, CommonCode.SERVICE_UNAVAILABLE, "文件存储服务暂不可用"),
    BusinessCode.LANGCHAIN_UNAVAILABLE: CodeSpec(BusinessCode.LANGCHAIN_UNAVAILABLE, CommonCode.SERVICE_UNAVAILABLE, "LangChain 服务暂不可用"),
    BusinessCode.TEXT_EMBEDDING_ERROR: CodeSpec(BusinessCode.TEXT_EMBEDDING_ERROR, CommonCode.BAD_GATEWAY, "文本向量计算异常"),
}


def resolve_code(code: int | IntEnum) -> CodeSpec:
    value = int(code)
    return CODE_SPECS.get(value, CODE_SPECS[CommonCode.INTERNAL_SERVER_ERROR])

def message_for_http_status(status_code: int) -> str:
    spec = CODE_SPECS.get(status_code)
    if spec is not None:
        return spec.message
    if 400 <= status_code < 500:
        return "请求不合法"
    return CODE_SPECS[CommonCode.INTERNAL_SERVER_ERROR].message
