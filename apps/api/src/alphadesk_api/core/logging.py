"""Structured JSON logging without sensitive configuration values."""

import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from alphadesk_api.core.config import Settings

correlation_id_context: ContextVar[str] = ContextVar("correlation_id", default="-")


def set_correlation_id(value: str) -> Token[str]:
    return correlation_id_context.set(value)


def reset_correlation_id(token: Token[str]) -> None:
    correlation_id_context.reset(token)


class JsonFormatter(logging.Formatter):
    """Serialize a stable set of log attributes as JSON."""

    def __init__(self, *, service: str, environment: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service,
            "environment": self.environment,
            "correlation_id": getattr(record, "correlation_id", correlation_id_context.get()),
            "request_method": getattr(record, "request_method", None),
            "request_path": getattr(record, "request_path", None),
            "status_code": getattr(record, "status_code", None),
            "duration_ms": getattr(record, "duration_ms", None),
        }
        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings: Settings) -> None:
    """Configure the root logger once for the application process."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service=settings.app_name, environment=settings.environment))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)
