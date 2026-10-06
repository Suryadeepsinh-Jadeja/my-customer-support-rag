"""Request dependencies: the database session and the authenticated user.

Authentication accepts either `Authorization: Bearer <token>` (API clients) or the
httpOnly `access_token` cookie (browser). Cookie-authenticated requests that change
state must also send `X-CSRF-Token` matching the `csrf_token` cookie.
"""

import secrets

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import CsrfError, NotAuthenticatedError, PermissionDeniedError
from app.core.logging import user_id_var
from app.core.security import decode_access_token
from app.db.database import get_db
from app.db.models import Role, User
from app.db.repositories.user_repository import UserRepository

ACCESS_COOKIE = "access_token"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    return None


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = _bearer_token(request)
    if token is None:
        token = request.cookies.get(ACCESS_COOKIE)
        if token and request.method not in _SAFE_METHODS:
            cookie = request.cookies.get(CSRF_COOKIE, "")
            header = request.headers.get(CSRF_HEADER, "")
            if not cookie or not secrets.compare_digest(cookie, header):
                raise CsrfError()
    if not token:
        raise NotAuthenticatedError()

    claims = decode_access_token(token)
    if claims is None:
        raise NotAuthenticatedError("Your session has expired. Please sign in again.")

    user = await UserRepository(db).get(claims.user_id)
    if user is None or not user.is_active or user.token_version != claims.version:
        raise NotAuthenticatedError("Your session has expired. Please sign in again.")

    user_id_var.set(str(user.id))
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.ADMIN:
        raise PermissionDeniedError()
    return user
