import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.idempotency import idempotent
from app.core import rate_limit
from app.core.errors import InvalidRequestError
from app.db.database import get_db
from app.db.models import BookingKind, BookingStatus, ConfirmationRequest, User
from app.providers import ProviderError
from app.schemas.booking import BookingOut, ConfirmationOut, ModifyRequest
from app.services.booking_service import BookingService

router = APIRouter(prefix="/bookings", tags=["bookings"])

BOOKING_RATE_LIMIT_PER_MINUTE = 20


def _confirmation(c: ConfirmationRequest) -> ConfirmationOut:
    return ConfirmationOut(confirmation_id=c.id, action=c.action, summary=c.summary,
                           expires_at=c.expires_at)


@router.get("", response_model=list[BookingOut], summary="Your bookings")
async def list_bookings(kind: BookingKind | None = None, status: BookingStatus | None = None,
                        user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    return [BookingOut.from_booking(b)
            for b in await BookingService(db, user).bookings(kind, status)]


@router.get("/{booking_id}", response_model=BookingOut, summary="One booking")
async def get_booking(booking_id: uuid.UUID, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    return BookingOut.from_booking(await BookingService(db, user).get(booking_id))


@router.post("/{booking_id}/cancel", response_model=ConfirmationOut,
             summary="Request a cancellation (returns a confirmation to approve)")
async def cancel_booking(booking_id: uuid.UUID, request: Request,
                         user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """Nothing is cancelled yet: the response shows the provider's refund quote; approve it
    with `POST /api/chat/confirm`. Supports `Idempotency-Key`."""
    rate_limit.enforce("booking", str(user.id), BOOKING_RATE_LIMIT_PER_MINUTE, 60)

    async def run() -> ConfirmationOut:
        try:
            confirmation = await BookingService(db, user).propose_cancel(booking_id, None)
        except ProviderError as exc:
            raise InvalidRequestError(exc.message) from exc
        await db.commit()
        return _confirmation(confirmation)

    return await idempotent(request, db, user, None, run)


@router.post("/{booking_id}/modify", response_model=ConfirmationOut,
             summary="Request a date change (returns a confirmation to approve)")
async def modify_booking(booking_id: uuid.UUID, body: ModifyRequest, request: Request,
                         user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """Supports `Idempotency-Key`."""
    rate_limit.enforce("booking", str(user.id), BOOKING_RATE_LIMIT_PER_MINUTE, 60)

    async def run() -> ConfirmationOut:
        try:
            confirmation = await BookingService(db, user).propose_modify(
                booking_id, body.start_date, body.end_date, None)
        except ProviderError as exc:
            raise InvalidRequestError(exc.message) from exc
        await db.commit()
        return _confirmation(confirmation)

    return await idempotent(request, db, user, body.model_dump(mode="json"), run)
