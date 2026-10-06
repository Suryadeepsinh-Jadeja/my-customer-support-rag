"""Application settings, read from environment variables (and `.env` in development)."""

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # backend/.env, wherever the process is started from; real env vars take precedence.
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    APP_NAME: str = "AI Travel Assistant"
    APP_ENV: Literal["development", "test", "production"] = "development"

    DATABASE_URL: str = "postgresql+asyncpg://travel:travel@localhost:5432/travel"
    DATABASE_ECHO: bool = False

    # Signing key for access tokens. Required in production; generated per process otherwise.
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = Field(default=60, ge=5, le=24 * 60)

    # Cookies are Secure by default outside development.
    COOKIE_SECURE: bool | None = None
    COOKIE_DOMAIN: str | None = None

    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Sign-in protection
    LOGIN_MAX_ATTEMPTS: int = Field(default=5, ge=1)
    LOGIN_LOCKOUT_MINUTES: int = Field(default=15, ge=1)
    AUTH_RATE_LIMIT_PER_MINUTE: int = Field(default=10, ge=1)

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "text"] | None = None

    # Used from phase 4 onwards; reported by /ready.
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash"

    @model_validator(mode="after")
    def _check_secrets(self) -> "Settings":
        if not self.JWT_SECRET:
            if self.APP_ENV == "production":
                raise ValueError("JWT_SECRET must be set in production")
            # Tokens stop working on restart, which is acceptable outside production.
            self.JWT_SECRET = secrets.token_urlsafe(48)
        elif self.APP_ENV == "production" and len(self.JWT_SECRET) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def cookie_secure(self) -> bool:
        if self.COOKIE_SECURE is not None:
            return self.COOKIE_SECURE
        return self.APP_ENV != "development" and self.APP_ENV != "test"

    @property
    def log_format(self) -> str:
        return self.LOG_FORMAT or ("json" if self.is_production else "text")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def database_backend(self) -> str:
        return self.DATABASE_URL.split(":", 1)[0].split("+", 1)[0]


@lru_cache
def get_settings() -> Settings:
    return Settings()
