"""Structured logging with a per-request ID and user ID attached to every record."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)

logger = logging.getLogger("travel")

_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.user_id = user_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and value is not None:
                data[key] = value
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extras = " ".join(
            f"{k}={v}"
            for k, v in record.__dict__.items()
            if k not in _RESERVED and v is not None
        )
        line = f"{record.levelname:<7} {record.name}: {record.getMessage()}"
        if extras:
            line = f"{line} | {extras}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def configure_logging(level: str, fmt: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(_ContextFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Request logging is done by our middleware.
    logging.getLogger("uvicorn.access").disabled = True


def log_event(event: str, **fields: Any) -> None:
    """Log a structured event. Never pass raw PII; use `mask` first."""
    logger.info(event, extra={"event": event, **fields})


def mask(value: str | None, visible: int = 4) -> str | None:
    """Mask an identifier for logs/UI, keeping only the last `visible` characters."""
    if not value:
        return value
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * 4 + value[-visible:]


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return mask(email)
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"
