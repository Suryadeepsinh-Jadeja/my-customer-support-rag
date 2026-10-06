"""Registration, sign-in (with lockout) and credential changes."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import (
    AccountLockedError,
    ConflictError,
    InvalidCredentialsError,
)
from app.core.security import (
    create_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.db.models import User
from app.db.repositories.user_repository import UserRepository
from app.services import audit_service


@dataclass
class IssuedToken:
    user: User
    access_token: str
    expires_at: datetime


def _aware(value: datetime | None) -> datetime | None:
    # SQLite returns naive datetimes; everything is stored in UTC.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _issue(user: User) -> IssuedToken:
    token, expires = create_access_token(user.id, user.role.value, user.token_version)
    return IssuedToken(user=user, access_token=token, expires_at=expires)


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.settings = get_settings()

    async def register(self, email: str, password: str, full_name: str, ip: str) -> IssuedToken:
        if await self.users.get_by_email(email):
            raise ConflictError("An account with this email already exists.")
        user = await self.users.create(email, hash_password(password), full_name)
        user.last_login_at = datetime.now(UTC)
        await audit_service.record(self.session, "auth.register", user_id=user.id, ip_address=ip)
        await self.session.commit()
        return _issue(user)

    async def login(self, email: str, password: str, ip: str) -> IssuedToken:
        user = await self.users.get_by_email(email)
        now = datetime.now(UTC)

        locked_until = _aware(user.locked_until) if user else None
        if user and locked_until and locked_until > now:
            await audit_service.record(self.session, "auth.login", user_id=user.id,
                                       status="failure", ip_address=ip,
                                       details={"reason": "locked"})
            await self.session.commit()
            raise AccountLockedError()

        # verify_password runs a hash even for unknown emails, so timing reveals nothing.
        valid = verify_password(user.password_hash if user else None, password)
        if not user or not valid or not user.is_active:
            if user:
                user.failed_login_count += 1
                if user.failed_login_count >= self.settings.LOGIN_MAX_ATTEMPTS:
                    user.locked_until = now + timedelta(minutes=self.settings.LOGIN_LOCKOUT_MINUTES)
                    user.failed_login_count = 0
                await audit_service.record(self.session, "auth.login", user_id=user.id,
                                           status="failure", ip_address=ip,
                                           details={"reason": "bad_credentials"})
                await self.session.commit()
            raise InvalidCredentialsError()

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        await audit_service.record(self.session, "auth.login", user_id=user.id, ip_address=ip)
        await self.session.commit()
        return _issue(user)

    async def logout_everywhere(self, user: User, ip: str) -> None:
        user.token_version += 1
        await audit_service.record(self.session, "auth.logout_all", user_id=user.id, ip_address=ip)
        await self.session.commit()

    async def change_password(self, user: User, current: str, new: str, ip: str) -> IssuedToken:
        if not verify_password(user.password_hash, current):
            await audit_service.record(self.session, "auth.password_change", user_id=user.id,
                                       status="failure", ip_address=ip)
            await self.session.commit()
            raise InvalidCredentialsError("The current password is incorrect.")
        user.password_hash = hash_password(new)
        user.token_version += 1  # sign out other devices
        await audit_service.record(self.session, "auth.password_change", user_id=user.id,
                                   ip_address=ip)
        await self.session.commit()
        return _issue(user)
