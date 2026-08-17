from __future__ import annotations

import logging
from collections.abc import Mapping
from enum import IntEnum
from typing import Any

from app.backend.core.codes import BusinessCode, CommonCode, resolve_code


class AppError(Exception):
    """Expected application error with safe user-facing text and log context."""

    def __init__(self, code: int | IntEnum, *, message: str | None = None, context: Mapping[str, Any] | None = None, log_level: int = logging.WARNING) -> None:
        spec = resolve_code(code)
        self.code = int(code)
        self.http_status = int(spec.http_status)
        self.message = message or spec.message
        self.context = dict(context or {})
        self.log_level = log_level
        super().__init__(self.message)


class AuthenticationError(AppError):
    def __init__(self, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(CommonCode.UNAUTHORIZED, context=context)


class PermissionDeniedError(AppError):
    def __init__(self, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(CommonCode.FORBIDDEN, context=context)


class ResourceNotFoundError(AppError):
    def __init__(self, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(CommonCode.NOT_FOUND, context=context)


class ConflictError(AppError):
    def __init__(self, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(CommonCode.CONFLICT, context=context)


class DuplicatePaperError(AppError):
    def __init__(self, *, paper_name: str | None = None, fingerprint: str | None = None) -> None:
        context = {key: value for key, value in {"paper_name": paper_name, "fingerprint": fingerprint}.items() if value}
        super().__init__(BusinessCode.PAPER_ALREADY_EXISTS, context=context)


class PaperFormatUnsupportedError(AppError):
    def __init__(self, *, filename: str | None = None, content_type: str | None = None) -> None:
        context = {key: value for key, value in {"filename": filename, "content_type": content_type}.items() if value}
        super().__init__(BusinessCode.PAPER_FORMAT_UNSUPPORTED, context=context)


class SQLiteUnavailableError(AppError):
    def __init__(self, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(BusinessCode.SQLITE_UNAVAILABLE, context=context)


class QdrantUnavailableError(AppError):
    def __init__(self, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(BusinessCode.QDRANT_UNAVAILABLE, context=context)


class TextEmbeddingUnavailableError(AppError):
    def __init__(self, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(BusinessCode.TEXT_EMBEDDING_UNAVAILABLE, context=context)


class MinerUUnavailableError(AppError):
    def __init__(self, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(BusinessCode.MINERU_UNAVAILABLE, context=context)


class MinerUResultInvalidError(AppError):
    def __init__(self, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(BusinessCode.MINERU_RESULT_INVALID, context=context)

class FileStorageUnavailableError(AppError):
    def __init__(self, *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(BusinessCode.FILE_STORAGE_UNAVAILABLE, context=context)