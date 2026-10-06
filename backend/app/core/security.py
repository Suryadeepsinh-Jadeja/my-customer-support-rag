"""Password hashing and access tokens."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

_hasher = PasswordHasher()
# Verified against unknown emails so sign-in takes the same time either way.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    role: str
    version: int


def create_access_token(user_id: uuid.UUID, role: str, version: int) -> tuple[str, datetime]:
    settings = get_settings()
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)
    payload = {
        "sub": str(user_id),
        "role": role,
        "ver": version,
        "type": "access",
        "iat": now,
        "exp": expires,
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM), expires


def decode_access_token(token: str) -> TokenClaims | None:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat", "ver", "type"]},
        )
        if payload["type"] != "access":
            return None
        return TokenClaims(
            user_id=uuid.UUID(payload["sub"]), role=payload.get("role", "user"),
            version=int(payload["ver"]),
        )
    except (jwt.PyJWTError, ValueError, KeyError):
        return None


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)
