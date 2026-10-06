import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TravelPreference, User, UserProfile


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def create(self, email: str, password_hash: str, full_name: str) -> User:
        user = User(email=email.lower(), password_hash=password_hash)
        user.profile = UserProfile(full_name=full_name)
        user.preferences = TravelPreference()
        self.session.add(user)
        await self.session.flush()
        return user

    async def count(self) -> int:
        return (await self.session.execute(select(func.count()).select_from(User))).scalar_one()
