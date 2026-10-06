# customer_support_chat/app/core/logger.py
import contextvars
import json
import logging

from .settings import get_settings

config = get_settings()

# Per-request context, attached to every log line emitted while handling it.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
conversation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "conversation_id", default="-"
)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.conversation_id = conversation_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "conversation_id": getattr(record, "conversation_id", "-"),
        }
        extra = getattr(record, "data", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extra = getattr(record, "data", None)
        if isinstance(extra, dict) and extra:
            line += " " + " ".join(f"{k}={v}" for k, v in extra.items())
        return line


logger = logging.getLogger("customer_support_chat")
logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
logger.propagate = False

if not logger.handlers:
    stream_handler = logging.StreamHandler()
    stream_handler.addFilter(_ContextFilter())
    if config.LOG_FORMAT == "json":
        stream_handler.setFormatter(_JsonFormatter())
    else:
        stream_handler.setFormatter(
            _TextFormatter(
                "%(asctime)s %(levelname)s [%(request_id)s|%(conversation_id)s] %(name)s - %(message)s"
            )
        )
    logger.addHandler(stream_handler)


def mask_id(value: str | None) -> str:
    """Mask customer identifiers before they reach the logs."""
    if not value:
        return "-"
    value = str(value)
    return "***" + value[-3:] if len(value) > 3 else "***"


def log_event(event: str, level: int = logging.INFO, **data) -> None:
    logger.log(level, event, extra={"data": data})
