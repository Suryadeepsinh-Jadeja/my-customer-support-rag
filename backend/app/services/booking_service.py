"""Search, book, modify and cancel, always through a user-approved confirmation.

Nothing that books, changes or cancels runs from a model's tool call or a UI click
directly. Those create a `ConfirmationRequest` (`propose_*`); only `confirm()` executes
it, after checking the owner, status, expiry and that the parameters are unchanged.
Each execution does the provider call, the database update and the audit entry in one
transaction, and a booking is only CONFIRMED when the provider returned success.
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.db.base import utcnow
from app.db.models import (
    Booking,
    BookingKind,
    BookingStatus,
    ConfirmationRequest,
    ConfirmationStatus,
    Message,
    User,
)
from app.providers import ProviderError, get_provider
from app.services import audit_service
from app.services.booking_state import ACTIVE, InvalidTransitionError, transition

logger = logging.getLogger("travel.bookings")

CONFIRMATION_TTL = timedelta(minutes=10)
DATE_CHANGES = {
    BookingKind.FLIGHT: ("date", None),
    BookingKind.HOTEL: ("check_in", "check_out"),
    BookingKind.CAR: ("pickup_date", "dropoff_date"),
    BookingKind.EXCURSION: ("date", None),
}


class ConfirmationError(ConflictError):
    code = "confirmation_invalid"
    message = "This confirmation can't be used."


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes; everything is stored in UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def params_hash(action: str, params: dict[str, Any]) -> str:
    raw = json.dumps({"action": action, "params": params}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def booking_card(b: Booking) -> dict[str, Any]:
    d = b.details or {}
    return {
        "type": "booking", "booking_id": str(b.id), "kind": b.kind.value,
        "status": b.status.value, "provider": b.provider,
        "test_booking": b.provider == "mock", "confirmation_number": b.provider_ref,
        "title": d.get("title"), "start_date": d.get("start_date"),
        "end_date": d.get("end_date"), "total_amount": b.total_amount,
        "currency": b.currency, "travellers": d.get("travellers", []),
        "refund": d.get("refund"),
    }


def confirmation_card(c: ConfirmationRequest) -> dict[str, Any]:
    return {"type": "confirmation", "confirmation_id": str(c.id), "action": c.action,
            "summary": c.summary, "expires_at": _aware(c.expires_at).isoformat()}


@dataclass
class Outcome:
    confirmation: ConfirmationRequest
    booking: Booking | None
    text: str
    message_type: str  # BOOKING_CONFIRMATION | BOOKING_STATUS | ERROR


class BookingService:
    def __init__(self, session: AsyncSession, user: User):
        self.session = session
        self.user = user

    # ------------------------------------------------------------------ read

    async def search(self, kind: BookingKind, params: dict[str, Any]) -> list[dict[str, Any]]:
        return await get_provider(kind.value).search(params)

    async def bookings(self, kind: BookingKind | None = None,
                   status: BookingStatus | None = None) -> list[Booking]:
        query = select(Booking).where(Booking.user_id == self.user.id)
        if kind:
            query = query.where(Booking.kind == kind)
        if status:
            query = query.where(Booking.status == status)
        query = query.order_by(Booking.travel_date.desc(), Booking.created_at.desc())
        return list((await self.session.execute(query.limit(200))).scalars())

    async def get(self, booking_id: uuid.UUID) -> Booking:
        booking = (await self.session.execute(
            select(Booking).where(Booking.id == booking_id, Booking.user_id == self.user.id)
        )).scalar_one_or_none()
        if booking is None:
            raise NotFoundError("Booking not found.")
        return booking

    # ------------------------------------------------------------- proposals

    async def propose_booking(self, kind: BookingKind, offer_id: str, travellers: list[str],
                              conversation_id: uuid.UUID | None) -> ConfirmationRequest:
        offer = await get_provider(kind.value).get_offer(offer_id)
        if date.fromisoformat(offer["start_date"]) < date.today():
            raise ProviderError("offer_expired", "That date is in the past.")
        summary = {"kind": kind.value, "title": offer["title"], "price": offer["price"],
                   "currency": offer["currency"], "start_date": offer["start_date"],
                   "end_date": offer["end_date"], "travellers": travellers,
                   "test_booking": offer.get("test_booking", False), "offer": offer}
        params = {"kind": kind.value, "offer_id": offer_id, "travellers": travellers,
                  "price": offer["price"]}
        return await self._new_confirmation("book", params, summary, conversation_id)

    async def propose_cancel(self, booking_id: uuid.UUID,
                             conversation_id: uuid.UUID | None) -> ConfirmationRequest:
        booking = await self._active(booking_id)
        quote = await get_provider(booking.kind.value).refund_quote(booking.details,
                                                                    booking.total_amount)
        summary = {"booking": booking_card(booking), "refund": quote}
        return await self._new_confirmation("cancel", {"booking_id": str(booking.id)},
                                            summary, conversation_id)

    async def propose_modify(self, booking_id: uuid.UUID, start_date: date,
                             end_date: date | None,
                             conversation_id: uuid.UUID | None) -> ConfirmationRequest:
        booking = await self._active(booking_id)
        changes = self._changes(booking, start_date, end_date)
        new = await get_provider(booking.kind.value).modify_quote(booking.details, changes)
        summary = {"booking": booking_card(booking),
                   "new": {"title": new["title"], "start_date": new["start_date"],
                           "end_date": new["end_date"], "price": new["price"],
                           "currency": new["currency"]},
                   "price_difference": round(new["price"] - booking.total_amount, 2)}
        return await self._new_confirmation(
            "modify", {"booking_id": str(booking.id), "changes": changes}, summary,
            conversation_id)

    async def _active(self, booking_id: uuid.UUID) -> Booking:
        booking = await self.get(booking_id)
        if booking.status not in ACTIVE:
            raise InvalidTransitionError(
                f"This booking is {booking.status.value.replace('_', ' ')}, so it can't be "
                "changed or cancelled.")
        return booking

    @staticmethod
    def _changes(booking: Booking, start: date, end: date | None) -> dict[str, str]:
        start_key, end_key = DATE_CHANGES[booking.kind]
        changes = {start_key: start.isoformat()}
        if end_key:
            if end is None:  # keep the same length of stay or rental
                old_start = date.fromisoformat(booking.details["start_date"])
                old_end = date.fromisoformat(booking.details["end_date"])
                end = start + (old_end - old_start)
            changes[end_key] = end.isoformat()
        return changes

    async def _new_confirmation(self, action: str, params: dict[str, Any],
                                summary: dict[str, Any],
                                conversation_id: uuid.UUID | None) -> ConfirmationRequest:
        confirmation = ConfirmationRequest(
            user_id=self.user.id, conversation_id=conversation_id, action=action,
            params=params, params_hash=params_hash(action, params), summary=summary,
            status=ConfirmationStatus.PENDING, expires_at=utcnow() + CONFIRMATION_TTL)
        self.session.add(confirmation)
        await self.session.flush()
        await audit_service.record(self.session, f"booking.{action}_requested",
                                   user_id=self.user.id, resource_type="confirmation",
                                   resource_id=str(confirmation.id))
        return confirmation

    # ------------------------------------------------------------- execution

    async def confirm(self, confirmation_id: uuid.UUID, approved: bool) -> Outcome:
        c = (await self.session.execute(
            select(ConfirmationRequest).where(ConfirmationRequest.id == confirmation_id,
                                              ConfirmationRequest.user_id == self.user.id)
        )).scalar_one_or_none()
        if c is None:
            raise NotFoundError("Confirmation not found.")
        if c.status != ConfirmationStatus.PENDING:
            raise ConfirmationError(f"This request was already {c.status.value}.")
        if _aware(c.expires_at) < utcnow():
            c.status = ConfirmationStatus.EXPIRED
            await self.session.commit()
            raise ConfirmationError("This request has expired. Please ask again.")
        if params_hash(c.action, c.params) != c.params_hash:
            raise ConfirmationError("This request was changed and can't be used.")

        # Single use: only one caller can move it out of "pending".
        new_status = ConfirmationStatus.CONFIRMED if approved else ConfirmationStatus.DECLINED
        claimed = await self.session.execute(
            update(ConfirmationRequest)
            .where(ConfirmationRequest.id == c.id,
                   ConfirmationRequest.status == ConfirmationStatus.PENDING)
            .values(status=new_status, updated_at=utcnow())
            .execution_options(synchronize_session=False))
        if claimed.rowcount != 1:  # type: ignore[attr-defined]
            raise ConfirmationError("This request was already handled.")
        c.status = new_status

        booking: Booking | None = None
        if not approved:
            text, ok = "Okay, I haven't changed anything.", True
            await audit_service.record(self.session, f"booking.{c.action}_declined",
                                       user_id=self.user.id, resource_type="confirmation",
                                       resource_id=str(c.id))
        elif c.action == "book":
            booking, text, ok = await self._book(c)
        elif c.action == "cancel":
            booking, text, ok = await self._cancel(uuid.UUID(c.params["booking_id"]))
        else:
            booking, text, ok = await self._modify(uuid.UUID(c.params["booking_id"]),
                                                   c.params["changes"])

        message_type = ("ERROR" if not ok else "BOOKING_CONFIRMATION"
                        if c.action == "book" and approved else "BOOKING_STATUS")
        if c.conversation_id:  # the outcome shows up in the conversation history too
            self.session.add(Message(
                conversation_id=c.conversation_id, role="assistant", content=text,
                payload={"type": message_type, "sources": [],
                         "cards": [booking_card(booking)] if booking else [],
                         "agent": "booking"}))
        await self.session.commit()
        return Outcome(c, booking, text, message_type)

    async def _book(self, c: ConfirmationRequest) -> tuple[Booking, str, bool]:
        kind = BookingKind(c.params["kind"])
        offer = c.summary["offer"]
        provider = get_provider(kind.value)
        booking = Booking(
            user_id=self.user.id, kind=kind, provider=provider.name,
            status=BookingStatus.BOOKING, travel_date=date.fromisoformat(offer["start_date"]),
            total_amount=c.params["price"], currency=offer["currency"],
            details=offer | {"travellers": c.params["travellers"]})
        self.session.add(booking)
        await self.session.flush()
        try:
            current = await provider.get_offer(c.params["offer_id"])
            booking.provider_ref = await provider.book(current, c.params["travellers"])
        except ProviderError as exc:
            transition(booking, BookingStatus.FAILED)
            booking.error_code = exc.code
            await self._audit("booking.create", booking, "failure", exc.code)
            return booking, f"The booking failed: {exc.message} Nothing was charged.", False
        transition(booking, BookingStatus.CONFIRMED)
        await self._audit("booking.create", booking)
        label = " (test booking)" if provider.name == "mock" else ""
        return booking, (f"Booked{label}: {offer['title']} on {offer['start_date']}. "
                         f"Confirmation number {booking.provider_ref}."), True

    async def _cancel(self, booking_id: uuid.UUID) -> tuple[Booking, str, bool]:
        booking = await self._active(booking_id)
        previous = booking.status
        transition(booking, BookingStatus.CANCELLATION_REQUESTED)
        provider = get_provider(booking.kind.value)
        try:
            refund = await provider.cancel(booking.provider_ref or "", booking.details,
                                           booking.total_amount)
        except ProviderError as exc:
            transition(booking, previous)
            await self._audit("booking.cancel", booking, "failure", exc.code)
            return booking, f"The cancellation failed: {exc.message} The booking is unchanged.", \
                False
        transition(booking, BookingStatus.CANCELLED)
        booking.details = booking.details | {"refund": refund}
        await self._audit("booking.cancel", booking)
        return booking, (f"Cancelled {booking.details.get('title')}. Refund: "
                         f"{refund['refund_amount']:.2f} {refund['currency']}."), True

    async def _modify(self, booking_id: uuid.UUID,
                      changes: dict[str, str]) -> tuple[Booking, str, bool]:
        booking = await self._active(booking_id)
        previous = booking.status
        transition(booking, BookingStatus.MODIFICATION_REQUESTED)
        provider = get_provider(booking.kind.value)
        try:
            new = await provider.modify(booking.provider_ref or "", booking.details, changes)
        except ProviderError as exc:
            transition(booking, previous)
            await self._audit("booking.modify", booking, "failure", exc.code)
            return booking, f"The change failed: {exc.message} The booking is unchanged.", False
        transition(booking, BookingStatus.MODIFIED)
        booking.details = new | {
            "travellers": booking.details.get("travellers", []),
            "modified_from": {"start_date": booking.details.get("start_date"),
                              "price": booking.total_amount}}
        booking.total_amount = new["price"]
        booking.travel_date = date.fromisoformat(new["start_date"])
        await self._audit("booking.modify", booking)
        return booking, (f"Changed {new['title']} to {new['start_date']}. New total "
                         f"{new['price']:.2f} {new['currency']}."), True

    async def _audit(self, action: str, booking: Booking, status: str = "success",
                     error: str | None = None) -> None:
        await audit_service.record(
            self.session, action, user_id=self.user.id, status=status,
            resource_type="booking", resource_id=str(booking.id),
            details={"kind": booking.kind.value, "provider": booking.provider,
                     "booking_status": booking.status.value,
                     **({"error_code": error} if error else {})})
