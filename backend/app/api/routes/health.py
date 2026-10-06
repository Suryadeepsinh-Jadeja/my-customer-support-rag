"""Liveness (/health) and readiness (/ready) probes. Neither exposes secrets."""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core import rate_limit
from app.core.config import get_settings
from app.db.database import get_engine
from app.services.malware import get_scanner
from app.services.ocr import get_ocr
from app.services.storage import get_storage

router = APIRouter(tags=["health"])
logger = logging.getLogger("travel.health")


@router.get("/health", summary="Liveness: the process is up")
async def health():
    return {"status": "ok"}


async def readiness() -> dict:
    """{"status": "ready" | "not_ready", "checks": {...}}; also shown in the admin panel."""
    settings = get_settings()
    checks: dict[str, dict] = {}

    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
            checks["database"] = {"ok": True, "backend": settings.database_backend}
            if settings.database_backend == "postgresql":
                found = (await conn.execute(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                )).first()
                checks["vector_store"] = {"ok": found is not None, "backend": "pgvector"}
    except Exception as exc:
        logger.warning("Readiness: database unreachable (%s)", type(exc).__name__)
        checks["database"] = {"ok": False, "backend": settings.database_backend}

    checks["object_storage"] = {
        "ok": await get_storage().check(),
        "backend": settings.STORAGE_BACKEND,
        "encrypted": bool(settings.STORAGE_ENCRYPTION_KEY),
    }

    # Reported for operators; documents still process (with reduced capability) without them.
    ocr = get_ocr()
    checks["ocr"] = {"ok": True, "provider": ocr.name if ocr else "unavailable"}
    checks["malware_scanner"] = {"ok": True, "provider": get_scanner().name}
    checks["llm"] = {"ok": True, "configured": bool(settings.GEMINI_API_KEY)}
    checks["worker"] = {"ok": True, "mode": settings.WORKER_MODE}

    if isinstance(rate_limit.limiter, rate_limit.RedisRateLimiter):
        try:
            await rate_limit.limiter.redis.ping()
            checks["rate_limiter"] = {"ok": True, "backend": "redis"}
        except Exception:
            logger.warning("readiness: redis unavailable")
            checks["rate_limiter"] = {"ok": False, "backend": "redis"}
    else:
        checks["rate_limiter"] = {"ok": True, "backend": "memory"}

    ok = all(c["ok"] for c in checks.values())
    return {"status": "ready" if ok else "not_ready", "checks": checks}


@router.get("/ready", summary="Readiness: dependencies are reachable and configured")
async def ready():
    result = await readiness()
    return JSONResponse(status_code=200 if result["status"] == "ready" else 503, content=result)
