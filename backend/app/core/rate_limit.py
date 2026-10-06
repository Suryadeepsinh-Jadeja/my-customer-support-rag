"""Sliding-window rate limiting.

`InMemoryRateLimiter` is per process. With several API workers or instances, swap in a
Redis-backed implementation of `RateLimiter` (planned with the Redis service in phase 9).
"""

import threading
import time
from collections import deque
from typing import Protocol

from fastapi import Request

from app.core.errors import RateLimitedError


class RateLimiter(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int) -> float | None:
        """Record a hit. Return None if allowed, else seconds until the next allowed hit."""
        ...


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> float | None:
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


limiter: RateLimiter = InMemoryRateLimiter()


def client_ip(request: Request) -> str:
    # Uvicorn's --proxy-headers sets request.client from X-Forwarded-For for trusted proxies.
    return request.client.host if request.client else "unknown"


def enforce(scope: str, key: str, limit: int, window_seconds: int = 60) -> None:
    retry_after = limiter.hit(f"{scope}:{key}", limit, window_seconds)
    if retry_after is not None:
        raise RateLimitedError(headers={"Retry-After": str(max(1, int(retry_after) + 1))})
