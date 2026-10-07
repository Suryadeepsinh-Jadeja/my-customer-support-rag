"""Payment sessions for bookings.

Only a mock exists: it returns a test session that is immediately marked paid, so no card
data ever exists in this system. A real provider (e.g. Stripe Checkout in test mode) would
create a hosted session here and update the status from its webhook. The assistant only
ever sees the session status (via the booking card), never payment details.
"""

import secrets
from typing import Any

from app.core.config import get_settings
from app.db.models import Booking


async def create_payment_session(booking: Booking) -> dict[str, Any]:
    session_id = "ps_test_" + secrets.token_hex(8)
    return {
        "provider": "mock", "session_id": session_id, "status": "test_paid", "test": True,
        "amount": booking.total_amount, "currency": booking.currency,
        "url": f"{get_settings().FRONTEND_URL}/bookings/{booking.id}?payment={session_id}",
    }
