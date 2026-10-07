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
from app.services import audit_service, payment_service
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
        "test_booking": d.get("test_booking", b.provider == "mock"),
        "confirmation_number": b.provider_ref,
        "title": d.get("title"), "start_date": d.get("start_date"),
        "end_date": d.get("end_date"), "total_amount": b.total_amount,
        "currency": b.currency, "travellers": d.get("travellers", []),
        "refund": d.get("refund"),
        "payment_status": (d.get("payment") or {}).get("status"),
    }


def confirmation_card(c: ConfirmationRequest) -> dict[str, Any]:
    return {"type": "confirmation", "confirmation_id": str(c.id), "action": c.action,
            "summary": c.summary, "expires_at": _aware(c.expires_at).isoformat()}


@dataclass
class Outcome:
    confirmation: ConfirmationRequest
    booking: Booking | None
    text: str
    # BOOKING_CONFIRMATION | BOOKING_STATUS | ERROR, or CONFIRMATION_REQUEST when the
    # price changed and the user has to confirm again
    message_type: str
    cards: list[dict[str, Any]]


@dataclass
class _Done:
    booking: Booking | None
    text: str
    ok: bool
    reconfirm: ConfirmationRequest | None = None


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

    async def propose_booking(self, kind: BookingKind, offer_id: str,
                              travellers: list[dict[str, Any]],
                              conversation_id: uuid.UUID | None,
                              previous_price: float | None = None) -> ConfirmationRequest:
        """travellers: [{name, born_on?, gender?}]; only names are shown in the summary."""
        offer = await get_provider(kind.value).get_offer(offer_id)
        if date.fromisoformat(offer["start_date"]) < date.today():
            raise ProviderError("offer_expired", "That date is in the past.")
        summary = {"kind": kind.value, "title": offer["title"], "price": offer["price"],
                   "currency": offer["currency"], "start_date": offer["start_date"],
                   "end_date": offer["end_date"],
                   "travellers": [t["name"] for t in travellers],
                   "test_booking": offer.get("test_booking", False), "offer": offer}
        if previous_price is not None:
            summary["previous_price"] = previous_price
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

        if not approved:
            done = _Done(None, "Okay, I haven't changed anything.", True)
            await audit_service.record(self.session, f"booking.{c.action}_declined",
                                       user_id=self.user.id, resource_type="confirmation",
                                       resource_id=str(c.id))
        elif c.action == "book":
            done = await self._book(c)
        elif c.action == "cancel":
            done = await self._cancel(uuid.UUID(c.params["booking_id"]))
        else:
            done = await self._modify(c)

        if done.reconfirm is not None:
            message_type, cards = "CONFIRMATION_REQUEST", [confirmation_card(done.reconfirm)]
        else:
            message_type = ("ERROR" if not done.ok else "BOOKING_CONFIRMATION"
                            if c.action == "book" and approved else "BOOKING_STATUS")
            cards = [booking_card(done.booking)] if done.booking else []
        if c.conversation_id:  # the outcome shows up in the conversation history too
            self.session.add(Message(
                conversation_id=c.conversation_id, role="assistant", content=done.text,
                payload={"type": message_type, "sources": [], "cards": cards,
                         "agent": "booking"}))
        await self.session.commit()
        return Outcome(c, done.booking, done.text, message_type, cards)

    async def _supersede(self, c: ConfirmationRequest, old: float, new: float,
                         currency: str, reconfirm: ConfirmationRequest) -> "_Done":
        """The price moved since the user saw it: book nothing and ask again (§61)."""
        c.status = ConfirmationStatus.EXPIRED
        await audit_service.record(self.session, f"booking.{c.action}_price_changed",
                                   user_id=self.user.id, resource_type="confirmation",
                                   resource_id=str(c.id))
        return _Done(None, f"The price changed from {old:.2f} to {new:.2f} {currency}. "
                           "Nothing was booked or charged. Confirm again to continue at the "
                           "new price.", True, reconfirm)

    async def _book(self, c: ConfirmationRequest) -> "_Done":
        kind = BookingKind(c.params["kind"])
        provider = get_provider(kind.value)
        try:
            offer = await provider.get_offer(c.params["offer_id"])  # price revalidation
        except ProviderError as exc:
            return _Done(None, f"{exc.message} Nothing was booked.", False)
        if offer["price"] != c.params["price"]:
            reconfirm = await self.propose_booking(kind, c.params["offer_id"],
                                                   c.params["travellers"], c.conversation_id,
                                                   previous_price=c.params["price"])
            return await self._supersede(c, c.params["price"], offer["price"],
                                         offer["currency"], reconfirm)

        names = [t["name"] for t in c.params["travellers"]]
        booking = Booking(
            user_id=self.user.id, kind=kind, provider=provider.name,
            status=BookingStatus.BOOKING, travel_date=date.fromisoformat(offer["start_date"]),
            total_amount=offer["price"], currency=offer["currency"],
            details=offer | {"travellers": names})
        self.session.add(booking)
        await self.session.flush()
        contact = {"email": self.user.email,
                   "phone": self.user.profile.phone if self.user.profile else None}
        try:
            result = await provider.book(offer, c.params["travellers"], contact)
        except ProviderError as exc:
            transition(booking, BookingStatus.FAILED)
            booking.error_code = exc.code
            await self._audit("booking.create", booking, "failure", exc.code)
            return _Done(booking, f"The booking failed: {exc.message} Nothing was charged.",
                         False)
        booking.provider_ref = result["reference"]
        transition(booking, BookingStatus.CONFIRMED)
        payment = await payment_service.create_payment_session(booking)
        booking.details = booking.details | {k: v for k, v in result.items()
                                             if k != "reference"} | {"payment": payment}
        await self._audit("booking.create", booking)
        label = " (test booking)" if offer.get("test_booking") else ""
        return _Done(booking, f"Booked{label}: {offer['title']} on {offer['start_date']}. "
                              f"Confirmation number {booking.provider_ref}.", True)

    async def _cancel(self, booking_id: uuid.UUID) -> "_Done":
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
            return _Done(booking, f"The cancellation failed: {exc.message} The booking is "
                                  "unchanged.", False)
        transition(booking, BookingStatus.CANCELLED)
        booking.details = booking.details | {"refund": refund}
        await self._audit("booking.cancel", booking)
        return _Done(booking, f"Cancelled {booking.details.get('title')}. Refund: "
                              f"{refund['refund_amount']:.2f} {refund['currency']}.", True)

    async def _modify(self, c: ConfirmationRequest) -> "_Done":
        booking = await self._active(uuid.UUID(c.params["booking_id"]))
        changes = c.params["changes"]
        provider = get_provider(booking.kind.value)
        quoted = c.summary["new"]["price"]
        try:
            current = await provider.modify_quote(booking.details, changes)
        except ProviderError as exc:
            return _Done(booking, f"The change failed: {exc.message} The booking is "
                                  "unchanged.", False)
        if current["price"] != quoted:
            start_key, end_key = DATE_CHANGES[booking.kind]
            reconfirm = await self.propose_modify(
                booking.id, date.fromisoformat(changes[start_key]),
                date.fromisoformat(changes[end_key]) if end_key else None, c.conversation_id)
            return await self._supersede(c, quoted, current["price"], current["currency"],
                                         reconfirm)

        previous = booking.status
        transition(booking, BookingStatus.MODIFICATION_REQUESTED)
        try:
            new = await provider.modify(booking.provider_ref or "", booking.details, changes)
        except ProviderError as exc:
            transition(booking, previous)
            await self._audit("booking.modify", booking, "failure", exc.code)
            return _Done(booking, f"The change failed: {exc.message} The booking is "
                                  "unchanged.", False)
        transition(booking, BookingStatus.MODIFIED)
        booking.details = new | {
            "travellers": booking.details.get("travellers", []),
            "payment": booking.details.get("payment"),
            "modified_from": {"start_date": booking.details.get("start_date"),
                              "price": booking.total_amount}}
        booking.total_amount = new["price"]
        booking.travel_date = date.fromisoformat(new["start_date"])
        await self._audit("booking.modify", booking)
        return _Done(booking, f"Changed {new['title']} to {new['start_date']}. New total "
                              f"{new['price']:.2f} {new['currency']}.", True)

    async def _audit(self, action: str, booking: Booking, status: str = "success",
                     error: str | None = None) -> None:
        await audit_service.record(
            self.session, action, user_id=self.user.id, status=status,
            resource_type="booking", resource_id=str(booking.id),
            details={"kind": booking.kind.value, "provider": booking.provider,
                     "booking_status": booking.status.value,
                     **({"error_code": error} if error else {})})
