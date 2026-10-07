"""Bookings and the confirmation requests that guard every booking action.

All booking kinds share one table (`kind` + a `details` JSON snapshot of the offer)
instead of separate FlightBooking/HotelBooking/... tables: the UI and the agents only need
a few common columns, and the per-kind details are display data.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, str_enum, utcnow


class BookingKind(enum.StrEnum):
    FLIGHT = "flight"
    HOTEL = "hotel"
    CAR = "car"
    EXCURSION = "excursion"


class BookingStatus(enum.StrEnum):
    SEARCHING = "searching"
    PRICE_CHECK = "price_check"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    BOOKING = "booking"
    CONFIRMED = "confirmed"
    MODIFICATION_REQUESTED = "modification_requested"
    MODIFIED = "modified"
    CANCELLATION_REQUESTED = "cancellation_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


class Booking(UUIDPk, Timestamps, Base):
    __tablename__ = "bookings"
    __table_args__ = (Index("ix_bookings_user_travel_date", "user_id", "travel_date"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    kind: Mapped[BookingKind] = mapped_column(str_enum(BookingKind, "booking_kind"))
    provider: Mapped[str] = mapped_column(String(32))  # "mock" = test booking
    provider_ref: Mapped[str | None] = mapped_column(String(64))  # confirmation number
    status: Mapped[BookingStatus] = mapped_column(str_enum(BookingStatus, "booking_status"))
    travel_date: Mapped[date | None] = mapped_column(Date)
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False))
    currency: Mapped[str] = mapped_column(String(3))
    details: Mapped[dict] = mapped_column(JSON, default=dict)  # offer snapshot, passengers
    error_code: Mapped[str | None] = mapped_column(String(64))


class ConfirmationStatus(enum.StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    EXPIRED = "expired"


class ConfirmationRequest(UUIDPk, Timestamps, Base):
    """A sensitive action proposed by the assistant (or the bookings UI), executed only
    when the same user approves it through POST /api/chat/confirm."""

    __tablename__ = "confirmation_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(32))  # book | cancel | modify
    params: Mapped[dict] = mapped_column(JSON)
    params_hash: Mapped[str] = mapped_column(String(64))
    summary: Mapped[dict] = mapped_column(JSON)  # what the user is shown
    status: Mapped[ConfirmationStatus] = mapped_column(
        str_enum(ConfirmationStatus, "confirmation_status"), default=ConfirmationStatus.PENDING
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyKey(Base):
    """The stored response to a booking request sent with an Idempotency-Key header, so a
    retried request returns the same result instead of acting twice."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_idempotency_keys_user_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
