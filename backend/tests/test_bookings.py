"""Mock providers, the booking state machine, confirmations, book/modify/cancel."""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select, update

from app.db.base import utcnow
from app.db.models import AuditLog, Booking, BookingStatus, ConfirmationRequest
from app.providers import ProviderError
from app.providers.mock import MockProvider
from app.services.booking_state import InvalidTransitionError, can_transition, transition
from tests.conftest import bearer, register
from tests.fake_llm import call, intent
from tests.test_chat import ask

TRAVEL_DATE = date.today() + timedelta(days=30)


# ------------------------------------------------------------ state machine


def test_state_transitions():
    S = BookingStatus
    assert can_transition(S.BOOKING, S.CONFIRMED) and can_transition(S.BOOKING, S.FAILED)
    assert can_transition(S.CONFIRMED, S.CANCELLATION_REQUESTED)
    assert can_transition(S.CANCELLATION_REQUESTED, S.CANCELLED)
    assert can_transition(S.MODIFIED, S.MODIFICATION_REQUESTED)
    assert not can_transition(S.CANCELLED, S.CONFIRMED)
    assert not can_transition(S.FAILED, S.CONFIRMED)
    assert not can_transition(S.BOOKING, S.CANCELLED)

    booking = Booking(status=S.CANCELLED)
    with pytest.raises(InvalidTransitionError):
        transition(booking, S.CONFIRMED)
    assert booking.status == S.CANCELLED


# ----------------------------------------------------------------- provider


async def test_mock_inventory_is_deterministic_and_resolvable():
    provider = MockProvider("flight")
    params = {"origin": "BOM", "destination": "LHR", "date": TRAVEL_DATE.isoformat(),
              "cabin": "economy"}
    offers = await provider.search(params)
    assert offers == await provider.search(params)
    assert all(o["provider"] == "mock" and o["test_booking"] for o in offers)
    assert await provider.get_offer(offers[2]["offer_id"]) == offers[2]

    # A date change keeps the same flight; only the price may move.
    later = await provider.search(params | {"date": (TRAVEL_DATE + timedelta(1)).isoformat()})
    assert [o["flight_number"] for o in later] == [o["flight_number"] for o in offers]

    for bad in ["flight|BOM|LHR|2026-12-01|economy|9", "hotel|x", "flight|BOM|LHR|x|economy|1",
                "flight|BOM|LHR|2026-12-01|luxury|1"]:
        with pytest.raises(ProviderError):
            await provider.get_offer(bad)


# ------------------------------------------------------------- chat flow


async def search_and_propose(client, token, llm) -> tuple[str, dict]:
    """Search flights, then ask to book the first offer. Returns (conversation, card)."""
    llm.script(intent("flight", needs_booking=True),
               call("search_flights", origin="bom", destination="LHR",
                    date=TRAVEL_DATE.isoformat()),
               "Here are some flights (test inventory).")
    found = await ask(client, token, f"Find me a flight to London on {TRAVEL_DATE}")
    assert found["message"]["type"] == "FLIGHT_RESULTS"
    offers = found["message"]["cards"]
    assert len(offers) == 5 and offers[0]["type"] == "flight_offer"
    assert offers[0]["origin"] == "BOM" and offers[0]["test_booking"]

    llm.script(intent("flight", continues_previous_topic=True),
               call("book_flight", offer_id=offers[0]["offer_id"]),
               "Please review and press Confirm.")
    proposed = await ask(client, token, "The first one please", found["conversation_id"])
    assert proposed["message"]["type"] == "CONFIRMATION_REQUEST"
    (card,) = proposed["message"]["cards"]
    assert card["action"] == "book"
    assert card["summary"]["travellers"] == ["Ana Traveller"]  # from the profile
    assert card["summary"]["price"] == offers[0]["price"]
    result = llm.tool_results()[-1].response["untrusted_data"]
    assert result["status"] == "awaiting_user_confirmation"
    assert "Nothing has been booked" in result["note"]
    return found["conversation_id"], card


async def confirm(client, token, confirmation_id, approved=True, expect=200):
    response = await client.post("/api/chat/confirm", headers=bearer(token), json={
        "confirmation_id": confirmation_id, "approved": approved})
    assert response.status_code == expect, response.text
    return response.json()


async def book(client, token, llm) -> dict:
    _, card = await search_and_propose(client, token, llm)
    return (await confirm(client, token, card["confirmation_id"]))["booking"]


async def test_search_book_confirm_list_cancel(client, user_token, llm, db_session):
    conversation_id, card = await search_and_propose(client, user_token, llm)
    # Proposing books nothing.
    assert (await client.get("/api/bookings", headers=bearer(user_token))).json() == []

    result = await confirm(client, user_token, card["confirmation_id"])
    assert result["status"] == "confirmed"
    assert result["message"]["type"] == "BOOKING_CONFIRMATION"
    assert "test booking" in result["message"]["text"]
    booking = result["booking"]
    assert booking["status"] == "confirmed" and booking["test_booking"]
    assert booking["confirmation_number"].startswith("MK")
    assert booking["details"]["travellers"] == ["Ana Traveller"]

    listed = (await client.get("/api/bookings", headers=bearer(user_token))).json()
    assert [b["id"] for b in listed] == [booking["id"]]
    history = (await client.get(f"/api/conversations/{conversation_id}",
                                headers=bearer(user_token))).json()["messages"]
    assert history[-1]["type"] == "BOOKING_CONFIRMATION"

    # Cancel via the bookings API: a confirmation with the provider's refund quote first.
    quote = (await client.post(f"/api/bookings/{booking['id']}/cancel",
                               headers=bearer(user_token))).json()
    assert quote["action"] == "cancel" and "refund_amount" in quote["summary"]["refund"]
    assert (await client.get(f"/api/bookings/{booking['id']}",
                             headers=bearer(user_token))).json()["status"] == "confirmed"
    cancelled = await confirm(client, user_token, quote["confirmation_id"])
    assert cancelled["booking"]["status"] == "cancelled"
    assert cancelled["booking"]["details"]["refund"] == quote["summary"]["refund"]
    assert cancelled["message"]["type"] == "BOOKING_STATUS"

    actions = set((await db_session.execute(select(AuditLog.action))).scalars())
    assert {"booking.book_requested", "booking.create", "booking.cancel_requested",
            "booking.cancel"} <= actions

    # A cancelled booking can't be cancelled again.
    again = await client.post(f"/api/bookings/{booking['id']}/cancel",
                              headers=bearer(user_token))
    assert again.status_code == 409


async def test_cancel_through_the_assistant_needs_confirmation(client, user_token, llm):
    booking = await book(client, user_token, llm)
    llm.script(intent("flight"), call("get_bookings"),
               call("cancel_booking", booking_id=booking["id"]),
               "Cancelling refunds ... Press Confirm to cancel.")
    body = await ask(client, user_token, "Cancel my flight")
    assert body["message"]["type"] == "CONFIRMATION_REQUEST"
    bookings, pending = [r.response["untrusted_data"] for r in llm.tool_results()]
    assert bookings["bookings"][0]["booking_id"] == booking["id"]
    assert pending["status"] == "awaiting_user_confirmation"
    assert pending["summary"]["refund"]["currency"] == "CHF"
    still = (await client.get(f"/api/bookings/{booking['id']}", headers=bearer(user_token)))
    assert still.json()["status"] == "confirmed"


async def test_modify_changes_the_dates(client, user_token, llm):
    booking = await book(client, user_token, llm)
    new_date = TRAVEL_DATE + timedelta(days=3)
    quote = (await client.post(f"/api/bookings/{booking['id']}/modify",
                               headers=bearer(user_token),
                               json={"start_date": new_date.isoformat()})).json()
    assert quote["summary"]["new"]["start_date"] == new_date.isoformat()
    result = await confirm(client, user_token, quote["confirmation_id"])
    changed = result["booking"]
    assert changed["status"] == "modified" and changed["start_date"] == new_date.isoformat()
    assert changed["details"]["flight_number"] == booking["details"]["flight_number"]
    assert changed["details"]["modified_from"]["start_date"] == TRAVEL_DATE.isoformat()
    assert changed["total_amount"] == quote["summary"]["new"]["price"]


async def test_declined_confirmation_books_nothing(client, user_token, llm):
    _, card = await search_and_propose(client, user_token, llm)
    result = await confirm(client, user_token, card["confirmation_id"], approved=False)
    assert result["status"] == "declined" and result["booking"] is None
    assert (await client.get("/api/bookings", headers=bearer(user_token))).json() == []


async def test_confirmations_are_single_use_owned_and_tamper_proof(client, user_token, llm,
                                                                  db_session):
    _, card = await search_and_propose(client, user_token, llm)
    cid = card["confirmation_id"]

    other = (await register(client, email="eve@example.com", name="Eve")).json()["access_token"]
    client.cookies.clear()
    await confirm(client, other, cid, expect=404)

    # Tampered parameters (e.g. a cheaper price written into the row) are refused.
    row = await db_session.get(ConfirmationRequest, uuid.UUID(cid))
    original = dict(row.params)
    await db_session.execute(update(ConfirmationRequest).where(ConfirmationRequest.id == row.id)
                             .values(params=original | {"price": 1.0}))
    await db_session.commit()
    assert (await confirm(client, user_token, cid, expect=409))["error"]["code"] == \
        "confirmation_invalid"
    await db_session.execute(update(ConfirmationRequest).where(ConfirmationRequest.id == row.id)
                             .values(params=original))
    await db_session.commit()

    await confirm(client, user_token, cid)
    second = await confirm(client, user_token, cid, expect=409)
    assert "already confirmed" in second["error"]["message"]
    assert len((await client.get("/api/bookings", headers=bearer(user_token))).json()) == 1


async def test_expired_confirmation_is_refused(client, user_token, llm, db_session):
    _, card = await search_and_propose(client, user_token, llm)
    await db_session.execute(
        update(ConfirmationRequest)
        .where(ConfirmationRequest.id == uuid.UUID(card["confirmation_id"]))
        .values(expires_at=utcnow() - timedelta(seconds=1)))
    await db_session.commit()
    body = await confirm(client, user_token, card["confirmation_id"], expect=409)
    assert "expired" in body["error"]["message"]
    db_session.expire_all()
    row = await db_session.get(ConfirmationRequest, uuid.UUID(card["confirmation_id"]))
    assert row.status.value == "expired"
    assert (await client.get("/api/bookings", headers=bearer(user_token))).json() == []


async def test_provider_failure_marks_the_booking_failed(client, user_token, llm,
                                                         monkeypatch):
    _, card = await search_and_propose(client, user_token, llm)

    async def refuse(self, offer, travellers, contact):
        raise ProviderError("sold_out", "The flight is sold out.")

    monkeypatch.setattr(MockProvider, "book", refuse)
    result = await confirm(client, user_token, card["confirmation_id"])
    assert result["message"]["type"] == "ERROR"
    assert result["message"]["text"] == ("The booking failed: The flight is sold out. "
                                         "Nothing was charged.")
    assert result["booking"]["status"] == "failed"
    assert result["booking"]["confirmation_number"] is None


async def test_other_users_cannot_see_or_change_bookings(client, user_token, llm):
    booking = await book(client, user_token, llm)
    other = (await register(client, email="eve@example.com", name="Eve")).json()["access_token"]
    client.cookies.clear()
    assert (await client.get("/api/bookings", headers=bearer(other))).json() == []
    for method, path, body in [
            ("GET", f"/api/bookings/{booking['id']}", None),
            ("POST", f"/api/bookings/{booking['id']}/cancel", None),
            ("POST", f"/api/bookings/{booking['id']}/modify",
             {"start_date": TRAVEL_DATE.isoformat()})]:
        response = await client.request(method, path, headers=bearer(other), json=body)
        assert response.status_code == 404, path

    # Nor through the assistant: the tool only sees the caller's bookings.
    llm.script(intent("flight"), call("cancel_booking", booking_id=booking["id"]), "No.")
    body = await ask(client, other, "Cancel booking " + booking["id"])
    assert body["message"]["type"] == "TEXT"
    assert llm.tool_results()[0].response["untrusted_data"] == {"error": "Booking not found."}


async def test_searches_reject_past_dates(client, user_token, llm):
    llm.script(intent("flight"),
               call("search_flights", origin="BOM", destination="LHR", date="2020-01-01"),
               "That date has passed.")
    await ask(client, user_token, "Flights in 2020")
    assert llm.tool_results()[0].response["untrusted_data"] == {
        "error": "That date is in the past."}
