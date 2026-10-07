"""Booking state machine: the only allowed status changes.

SEARCHING -> PRICE_CHECK -> AWAITING_CONFIRMATION -> BOOKING -> CONFIRMED
CONFIRMED / MODIFIED -> MODIFICATION_REQUESTED -> MODIFIED (or back on provider failure)
CONFIRMED / MODIFIED -> CANCELLATION_REQUESTED -> CANCELLED (or back on provider failure)
BOOKING -> FAILED; anything before BOOKING -> EXPIRED

Booking rows are created when the user confirms, so in practice they start at BOOKING;
the earlier states describe the search and confirmation steps before that.
"""

from app.core.errors import ConflictError
from app.db.models import Booking
from app.db.models import BookingStatus as S

TRANSITIONS: dict[S, set[S]] = {
    S.SEARCHING: {S.PRICE_CHECK, S.EXPIRED},
    S.PRICE_CHECK: {S.AWAITING_CONFIRMATION, S.EXPIRED},
    S.AWAITING_CONFIRMATION: {S.BOOKING, S.EXPIRED},
    S.BOOKING: {S.CONFIRMED, S.FAILED},
    S.CONFIRMED: {S.MODIFICATION_REQUESTED, S.CANCELLATION_REQUESTED},
    S.MODIFICATION_REQUESTED: {S.MODIFIED, S.CONFIRMED},
    S.MODIFIED: {S.MODIFICATION_REQUESTED, S.CANCELLATION_REQUESTED},
    S.CANCELLATION_REQUESTED: {S.CANCELLED, S.CONFIRMED, S.MODIFIED},
    S.CANCELLED: set(),
    S.FAILED: set(),
    S.EXPIRED: set(),
}

ACTIVE = {S.CONFIRMED, S.MODIFIED}


class InvalidTransitionError(ConflictError):
    code = "invalid_booking_state"
    message = "That isn't possible for this booking in its current state."


def can_transition(current: S, to: S) -> bool:
    return to in TRANSITIONS[current]


def transition(booking: Booking, to: S) -> None:
    if not can_transition(booking.status, to):
        raise InvalidTransitionError(
            f"A {booking.status.value.replace('_', ' ')} booking can't become "
            f"{to.value.replace('_', ' ')}.")
    booking.status = to
