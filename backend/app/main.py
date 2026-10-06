"""FastAPI application factory.

Run locally:  uvicorn app.main:app --reload
Docs:         /docs (Swagger UI) and /redoc
"""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, documents, health, search, users
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, logger
from app.db.database import dispose_engine
from app.middleware.body_limit import BodySizeLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.services import jobs


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logger.info("startup", extra={"env": settings.APP_ENV, "db": settings.database_backend,
                                  "worker": settings.WORKER_MODE})
    if settings.WORKER_MODE == "inline":
        jobs.kick_inline_worker()  # pick up anything queued before a restart
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL, settings.log_format)

    app = FastAPI(
        title=f"{settings.APP_NAME} API",
        version="0.1.0",
        description="Flights, hotels, cars, documents and travel support.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID",
                       "Idempotency-Key"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    # Uploads are the largest legitimate bodies; allow some room for multipart overhead.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_upload_bytes + 1024 * 1024)
    # Outermost, so every response (including errors and CORS) carries the request ID.
    app.add_middleware(RequestContextMiddleware, hsts=settings.is_production)
    register_error_handlers(app)

    api = APIRouter(prefix="/api")
    api.include_router(auth.router)
    api.include_router(users.router)
    api.include_router(documents.router)
    api.include_router(search.router)
    api.add_api_route("/health", health.health, methods=["GET"], tags=["health"],
                      summary="Liveness (same as /health)")
    app.include_router(api)
    app.include_router(health.router)
    return app


app = create_app()
