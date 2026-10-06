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
    # Shared rate limits across API processes; in-process limits when empty.
    REDIS_URL: str = ""
    CHAT_RATE_LIMIT_PER_HOUR: int = Field(default=200, ge=1)

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "text"] | None = None

    # Google Gemini
    GEMINI_API_KEY: str = ""
    # "fake": a rule-based stand-in for end-to-end tests and keyless demos (never production).
    LLM_PROVIDER: Literal["gemini", "fake"] = "gemini"
    GEMINI_MODEL: str = "gemini-3.5-flash"
    LLM_TIMEOUT_SECONDS: int = Field(default=60, ge=5)

    # Booking providers. Hotels, cars and excursions always use the mock; flights can use
    # Duffel (a duffel_test_ key gives Duffel's sandbox).
    FLIGHT_PROVIDER: Literal["mock", "duffel"] = "mock"
    DUFFEL_API_KEY: str = ""
    DUFFEL_BASE_URL: str = "https://api.duffel.com"

    # Object storage for uploaded files. "local" writes under STORAGE_LOCAL_PATH;
    # "s3" uses any S3-compatible service (AWS S3, MinIO, R2, GCS interop).
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_LOCAL_PATH: Path = BACKEND_DIR / "storage"
    OBJECT_STORAGE_ENDPOINT: str = ""
    OBJECT_STORAGE_REGION: str = "us-east-1"
    OBJECT_STORAGE_ACCESS_KEY: str = ""
    OBJECT_STORAGE_SECRET_KEY: str = ""
    OBJECT_STORAGE_BUCKET: str = "travel-documents"
    # Base64 of 32 random bytes; files are AES-256-GCM encrypted before they reach storage.
    # Required in production. Generate with:
    #   python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
    STORAGE_ENCRYPTION_KEY: str = ""

    # Uploads
    MAX_UPLOAD_MB: int = Field(default=15, ge=1, le=100)
    MAX_PDF_PAGES: int = Field(default=50, ge=1)
    MAX_DOCUMENTS_PER_USER: int = Field(default=200, ge=1)
    UPLOAD_RATE_LIMIT_PER_HOUR: int = Field(default=30, ge=1)

    # Malware scanning: "none" (development) or "clamav" (clamd over TCP).
    MALWARE_SCANNER: Literal["none", "clamav"] = "none"
    CLAMAV_HOST: str = "localhost"
    CLAMAV_PORT: int = 3310

    # OCR for scanned PDFs and images. "auto": Tesseract if installed, else Gemini vision.
    OCR_PROVIDER: Literal["auto", "tesseract", "gemini", "none"] = "auto"
    # Classification + field extraction. "auto": Gemini if a key is set, else rules.
    DOCUMENT_AI_PROVIDER: Literal["auto", "gemini", "rules"] = "auto"

    # Background jobs. "inline": the API process runs them (development);
    # "external": a separate `python -m app.worker` process does (production).
    WORKER_MODE: Literal["inline", "external"] = "inline"
    WORKER_POLL_SECONDS: float = Field(default=2.0, gt=0)

    @model_validator(mode="after")
    def _check_secrets(self) -> "Settings":
        if not self.JWT_SECRET:
            if self.APP_ENV == "production":
                raise ValueError("JWT_SECRET must be set in production")
            # Tokens stop working on restart, which is acceptable outside production.
            self.JWT_SECRET = secrets.token_urlsafe(48)
        elif self.APP_ENV == "production" and len(self.JWT_SECRET) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters in production")
        if self.APP_ENV == "production" and not self.STORAGE_ENCRYPTION_KEY:
            raise ValueError("STORAGE_ENCRYPTION_KEY must be set in production")
        if self.APP_ENV == "production" and self.LLM_PROVIDER == "fake":
            raise ValueError("LLM_PROVIDER=fake is for tests only, not production")
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

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
