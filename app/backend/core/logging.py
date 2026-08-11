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
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                    "level": level,
                },
            },
            "root": {
                "handlers": ["default"],
                "level": level,
            },
            "loggers": {
                "uvicorn": {
                    "handlers": ["default"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["default"],
                    "level": level,
                    "propagate": False,
                },
                # Access logging will be replaced by the project middleware later.
                "uvicorn.access": {
                    "handlers": ["default"],
                    "level": level,
                    "propagate": False,
                },
            },
        }
    )
