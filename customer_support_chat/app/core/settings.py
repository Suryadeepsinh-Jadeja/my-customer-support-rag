import os
from functools import lru_cache
from os import environ

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    value = environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _list(name: str, default: str) -> list[str]:
    return [item.strip() for item in environ.get(name, default).split(",") if item.strip()]


class Config:
    def __init__(self):
        # LLM
        self.GEMINI_API_KEY: str = environ.get("GEMINI_API_KEY", "").strip()
        self.GEMINI_MODEL: str = environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.LLM_TEMPERATURE: float = _float("LLM_TEMPERATURE", 0.2)
        self.LLM_TIMEOUT_SECONDS: int = _int("LLM_TIMEOUT_SECONDS", 60)
        self.LLM_MAX_RETRIES: int = _int("LLM_MAX_RETRIES", 2)

        # Data
        self.DATA_PATH: str = "./customer_support_chat/data"
        self.SQLITE_DB_PATH: str = environ.get(
            "SQLITE_DB_PATH", "./customer_support_chat/data/travel2.sqlite"
        )
        self.KNOWLEDGE_BASE_DIR: str = environ.get("KNOWLEDGE_BASE_DIR", "./knowledge_base")

        # Vector store. QDRANT_URL (server mode) takes precedence over
        # QDRANT_PATH (embedded local mode, no server required).
        self.QDRANT_URL: str = environ.get("QDRANT_URL", "").strip()
        self.QDRANT_API_KEY: str = environ.get("QDRANT_API_KEY", "").strip()
        self.QDRANT_PATH: str = environ.get(
            "QDRANT_PATH", "./customer_support_chat/data/qdrant_local"
        )

        # RAG
        self.RAG_TOP_K: int = _int("RAG_TOP_K", 4)
        self.RAG_CANDIDATES: int = _int("RAG_CANDIDATES", 12)
        self.RAG_RERANK: bool = _bool("RAG_RERANK", True)
        self.RAG_MIN_SCORE: float = _float("RAG_MIN_SCORE", 0.2)

        # API / sessions
        self.API_HOST: str = environ.get("API_HOST", "127.0.0.1")
        self.API_PORT: int = _int("API_PORT", 8000)
        self.CORS_ORIGINS: list[str] = _list(
            "CORS_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501"
        )
        self.REQUEST_TIMEOUT_SECONDS: int = _int("REQUEST_TIMEOUT_SECONDS", 120)
        self.SESSION_TTL_MINUTES: int = _int("SESSION_TTL_MINUTES", 120)
        # Failed sign-ins allowed per passenger ID within the lockout window.
        self.LOGIN_MAX_ATTEMPTS: int = _int("LOGIN_MAX_ATTEMPTS", 5)
        self.LOGIN_LOCKOUT_MINUTES: int = _int("LOGIN_LOCKOUT_MINUTES", 15)
        self.DEMO_PASSENGER_ID: str = environ.get("DEMO_PASSENGER_ID", "").strip()

        # Logging
        self.LOG_LEVEL: str = environ.get("LOG_LEVEL", "INFO").upper()
        self.LOG_FORMAT: str = environ.get("LOG_FORMAT", "text").lower()

        # Optional tracing
        self.LANGSMITH_TRACING: bool = _bool("LANGSMITH_TRACING", False) or _bool(
            "LANGCHAIN_TRACING_V2", False
        )
        self.LANGSMITH_API_KEY: str = (
            environ.get("LANGSMITH_API_KEY") or environ.get("LANGCHAIN_API_KEY") or ""
        ).strip()


def configure_tracing(config: "Config") -> bool:
    """LangSmith is optional infrastructure: enable it only when explicitly
    requested AND a key is present, otherwise force it off so the SDK never
    tries (and fails with 401) to upload runs."""
    enabled = config.LANGSMITH_TRACING and bool(config.LANGSMITH_API_KEY)
    for var in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        os.environ[var] = "true" if enabled else "false"
    return enabled


@lru_cache
def get_settings() -> Config:
    config = Config()
    configure_tracing(config)
    return config
