import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel

from app.db.models import Booking, BookingKind, BookingStatus
from app.schemas.chat import AssistantMessage
from app.schemas.common import UtcDatetime


class BookingOut(BaseModel):
    id: uuid.UUID
    kind: BookingKind
    status: BookingStatus
    provider: str
    test_booking: bool
    confirmation_number: str | None
    title: str | None
    start_date: str | None
    end_date: str | None
    total_amount: float
    currency: str
    details: dict[str, Any]
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @classmethod
    def from_booking(cls, b: Booking) -> "BookingOut":
        d = b.details or {}
        return cls(id=b.id, kind=b.kind, status=b.status, provider=b.provider,
                   test_booking=b.provider == "mock", confirmation_number=b.provider_ref,
                   title=d.get("title"), start_date=d.get("start_date"),
                   end_date=d.get("end_date"), total_amount=b.total_amount,
                   currency=b.currency, details=d, created_at=b.created_at,
                   updated_at=b.updated_at)


class ModifyRequest(BaseModel):
    start_date: dt.date
    end_date: dt.date | None = None


class ConfirmationOut(BaseModel):
    """What the confirmation dialog shows. Approve it with POST /api/chat/confirm."""

    confirmation_id: uuid.UUID
    action: str
    summary: dict[str, Any]
    expires_at: UtcDatetime


class ConfirmRequest(BaseModel):
    confirmation_id: uuid.UUID
    approved: bool


class ConfirmResponse(BaseModel):
    confirmation_id: uuid.UUID
    status: str
    message: AssistantMessage
    booking: BookingOut | None
