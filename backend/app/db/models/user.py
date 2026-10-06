import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk, str_enum


class Role(enum.StrEnum):
    USER = "user"
    ADMIN = "admin"


class CabinClass(enum.StrEnum):
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(str_enum(Role, "user_role"), default=Role.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bumped to invalidate every issued access token (sign out everywhere, password change).
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped["UserProfile"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    preferences: Mapped["TravelPreference"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )


class UserProfile(Timestamps, Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    full_name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str | None] = mapped_column(String(32))
    nationality: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2
    home_airport: Mapped[str | None] = mapped_column(String(3))  # IATA

    user: Mapped[User] = relationship(back_populates="profile")


class TravelPreference(Timestamps, Base):
    __tablename__ = "travel_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    preferred_airports: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_airlines: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_cabin: Mapped[CabinClass | None] = mapped_column(str_enum(CabinClass, "cabin_class"))
    seat_preference: Mapped[str | None] = mapped_column(String(32))
    meal_preference: Mapped[str | None] = mapped_column(String(64))
    # [{"airline": "LX", "number": "..."}]; numbers are masked whenever shown or logged.
    frequent_flyer_programs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="preferences")
