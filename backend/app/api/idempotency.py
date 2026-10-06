"""Idempotency-Key support for booking endpoints.

A request sent with `Idempotency-Key: <key>` stores its successful response. Sending the
same key again (same user, same request) returns the stored response without acting a
second time; reusing a key for a different request is refused. Errors aren't stored, so a
failed request can be retried with the same key.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, InvalidRequestError
from app.db.models import IdempotencyKey, User

HEADER = "Idempotency-Key"


async def idempotent(request: Request, db: AsyncSession, user: User, body: Any,
                     handler: Callable[[], Awaitable[BaseModel]]) -> BaseModel | JSONResponse:
    key = request.headers.get(HEADER)
    if key is None:
        return await handler()
    if not 1 <= len(key) <= 100:
        raise InvalidRequestError(f"{HEADER} must be 1 to 100 characters.")
    request_hash = hashlib.sha256(json.dumps(
        {"path": request.url.path, "body": body}, sort_keys=True, default=str).encode()
    ).hexdigest()

    async def stored() -> IdempotencyKey | None:
        return (await db.execute(select(IdempotencyKey).where(
            IdempotencyKey.user_id == user.id, IdempotencyKey.key == key))).scalar_one_or_none()

    def replay(row: IdempotencyKey) -> JSONResponse:
        if row.request_hash != request_hash:
            raise ConflictError(f"This {HEADER} was already used for a different request.")
        return JSONResponse(row.response, headers={"Idempotent-Replayed": "true"})

    if (row := await stored()) is not None:
        return replay(row)
    result = await handler()
    db.add(IdempotencyKey(user_id=user.id, key=key, request_hash=request_hash,
                          response=result.model_dump(mode="json")))
    try:
        await db.commit()
    except IntegrityError:  # a concurrent request with the same key finished first
        await db.rollback()
        if (row := await stored()) is not None:
            return replay(row)
        raise
    return result
