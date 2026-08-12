from __future__ import annotations

import logging
import logging.config

from app.backend.config import Settings
from app.backend.middleware.request_context import get_current_request_id


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_current_request_id()
        return True


def configure_logging(settings: Settings) -> None:
    """Configure one predictable logging setup for the application and Uvicorn."""

    level = settings.log_level
    log_dir = settings.project_path(settings.data_dir) / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    log_format = (
        "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s"
    )
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "request_id": {
                    "()": "app.backend.core.logging.RequestIdFilter",
                },
            },
            "formatters": {
                "default": {
                    "format": log_format,
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                    "level": level,
                },
                "file": {
                    "class": "logging.handlers.TimedRotatingFileHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                    "level": level,
                    "filename": str(log_file),
                    "when": "midnight",
                    "backupCount": 14,
                    "encoding": "utf-8",
                },
            },
            "root": {
                "handlers": ["console", "file"],
                "level": level,
            },
            "loggers": {
                "uvicorn": {
                    "handlers": ["console", "file"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["console", "file"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": [],
                    "level": "WARNING",
                    "propagate": False,
                },
                "httpx": {
                    "handlers": ["console", "file"],
                    "level": "WARNING",
                    "propagate": False,
                },
                "httpcore": {
                    "handlers": ["console", "file"],
                    "level": "WARNING",
                    "propagate": False,
                },
            },
        }
    )
