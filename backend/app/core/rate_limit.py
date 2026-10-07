"""Sliding-window rate limiting.

With `REDIS_URL` set (production, Docker), limits are shared by every API process and
instance through Redis sorted sets. Without it (local development, tests) an in-process
limiter is used. If Redis is unreachable, requests are allowed and a warning is logged:
an outage of the limiter must not take sign-in down.
"""

import logging
import secrets
import threading
import time
from collections import deque

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import RateLimitedError

logger = logging.getLogger("travel.rate_limit")


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    async def hit(self, key: str, limit: int, window_seconds: int) -> float | None:
        """Record a hit. None if allowed, else seconds until the next allowed hit."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return hits[0] + window_seconds - now
            hits.append(now)
            if len(self._hits) > 50_000:  # drop idle keys so memory stays bounded
                for k in [k for k, v in self._hits.items() if not v]:
                    del self._hits[k]
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class RedisRateLimiter:
    def __init__(self, client) -> None:
        self.redis = client

    async def hit(self, key: str, limit: int, window_seconds: int) -> float | None:
        name = f"ratelimit:{key}"
        now = time.time()
        member = f"{now:.6f}-{secrets.token_hex(4)}"
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(name, 0, now - window_seconds)
                pipe.zadd(name, {member: now})
                pipe.zcard(name)
                pipe.zrange(name, 0, 0, withscores=True)
                pipe.expire(name, window_seconds)
                _, _, count, oldest, _ = await pipe.execute()
            if count <= limit:
                return None
            await self.redis.zrem(name, member)  # a refused hit doesn't count
            return float(oldest[0][1]) + window_seconds - now
        except Exception as exc:  # fail open
            logger.warning("rate limiter unavailable", extra={"error": type(exc).__name__})
            return None


def _build():
    url = get_settings().REDIS_URL
    if not url:
        return InMemoryRateLimiter()
    import redis.asyncio as redis

    return RedisRateLimiter(redis.from_url(url))


limiter: InMemoryRateLimiter | RedisRateLimiter = _build()


def client_ip(request: Request) -> str:
    # Uvicorn's --proxy-headers sets request.client from X-Forwarded-For for trusted proxies.
    return request.client.host if request.client else "unknown"


async def enforce(scope: str, key: str, limit: int, window_seconds: int = 60) -> None:
    retry_after = await limiter.hit(f"{scope}:{key}", limit, window_seconds)
    if retry_after is not None:
        raise RateLimitedError(headers={"Retry-After": str(max(1, int(retry_after) + 1))})
