"""Phase 7: price revalidation, idempotency keys, payment sessions, traveller details."""

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.db.models import ConfirmationRequest
from app.providers.mock import MockProvider
from tests import samples
from tests.conftest import bearer
from tests.fake_llm import call, intent
from tests.test_bookings import TRAVEL_DATE, book, confirm, search_and_propose
from tests.test_chat import ask, upload


def bump_prices(monkeypatch, amount: float) -> None:
    original_get, original_quote = MockProvider.get_offer, MockProvider.modify_quote

    async def get_offer(self, offer_id):
        offer = await original_get(self, offer_id)
        return offer | {"price": round(offer["price"] + amount, 2)}

    async def modify_quote(self, details, changes):
        offer = await original_quote(self, details, changes)
        return offer | {"price": round(offer["price"] + amount, 2)}

    monkeypatch.setattr(MockProvider, "get_offer", get_offer)
    monkeypatch.setattr(MockProvider, "modify_quote", modify_quote)


async def test_price_change_needs_a_new_confirmation(client, user_token, llm, monkeypatch,
                                                     db_session):
    conversation_id, card = await search_and_propose(client, user_token, llm)
    old_price = card["summary"]["price"]
    bump_prices(monkeypatch, 25)

    result = await confirm(client, user_token, card["confirmation_id"])
    assert result["booking"] is None
    assert result["status"] == "expired"
    assert result["message"]["type"] == "CONFIRMATION_REQUEST"
    new_price = round(old_price + 25, 2)
    assert result["message"]["text"].startswith(
        f"The price changed from {old_price:.2f} to {new_price:.2f} USD. Nothing was booked")
    (again,) = result["message"]["cards"]
    assert again["summary"]["price"] == new_price
    assert again["summary"]["previous_price"] == old_price
    assert (await client.get("/api/bookings", headers=bearer(user_token))).json() == []
    history = (await client.get(f"/api/conversations/{conversation_id}",
                                headers=bearer(user_token))).json()["messages"]
    assert history[-1]["type"] == "CONFIRMATION_REQUEST"

    # Approving the new confirmation books at the new price.
    booked = await confirm(client, user_token, again["confirmation_id"])
    assert booked["booking"]["status"] == "confirmed"
    assert booked["booking"]["total_amount"] == new_price


async def test_date_change_price_moves_need_a_new_confirmation(client, user_token, llm,
                                                              monkeypatch):
    booking = await book(client, user_token, llm)
    quote = (await client.post(f"/api/bookings/{booking['id']}/modify",
                               headers=bearer(user_token), json={
                                   "start_date": (TRAVEL_DATE + timedelta(2)).isoformat()})).json()
    bump_prices(monkeypatch, 40)
    result = await confirm(client, user_token, quote["confirmation_id"])
    assert result["message"]["type"] == "CONFIRMATION_REQUEST"
    assert result["booking"] is None
    current = (await client.get(f"/api/bookings/{booking['id']}",
                                headers=bearer(user_token))).json()
    assert current["status"] == "confirmed" and current["start_date"] == TRAVEL_DATE.isoformat()


async def test_confirm_with_the_same_idempotency_key_returns_the_same_booking(
        client, user_token, llm):
    _, card = await search_and_propose(client, user_token, llm)
    headers = bearer(user_token) | {"Idempotency-Key": "confirm-123"}
    body = {"confirmation_id": card["confirmation_id"], "approved": True}

    first = await client.post("/api/chat/confirm", headers=headers, json=body)
    second = await client.post("/api/chat/confirm", headers=headers, json=body)
    assert first.status_code == second.status_code == 200
    assert second.headers["Idempotent-Replayed"] == "true"
    assert first.json() == second.json()
    assert len((await client.get("/api/bookings", headers=bearer(user_token))).json()) == 1

    # Without the key, a repeat is refused (the confirmation is single-use).
    assert (await client.post("/api/chat/confirm", headers=bearer(user_token),
                              json=body)).status_code == 409
    # The same key for a different request is refused.
    other = await client.post("/api/chat/confirm", headers=headers, json=body | {
        "confirmation_id": str(uuid.uuid4())})
    assert other.status_code == 409


async def test_cancel_request_with_the_same_key_creates_one_confirmation(
        client, user_token, llm, db_session):
    booking = await book(client, user_token, llm)
    headers = bearer(user_token) | {"Idempotency-Key": "cancel-1"}
    url = f"/api/bookings/{booking['id']}/cancel"
    first = (await client.post(url, headers=headers)).json()
    second = (await client.post(url, headers=headers)).json()
    assert first["confirmation_id"] == second["confirmation_id"]
    cancels = (await db_session.execute(select(ConfirmationRequest).where(
        ConfirmationRequest.action == "cancel"))).scalars().all()
    assert len(cancels) == 1


async def test_bookings_get_a_test_payment_session_the_model_sees_only_its_status(
        client, user_token, llm):
    booking = await book(client, user_token, llm)
    payment = booking["details"]["payment"]
    assert payment["status"] == "test_paid" and payment["test"] is True
    assert payment["session_id"].startswith("ps_test_")

    llm.script(intent("flight"), call("get_bookings"), "You have one booking.")
    await ask(client, user_token, "What have I booked?")
    (card,) = llm.tool_results()[0].response["untrusted_data"]["bookings"]
    assert card["payment_status"] == "test_paid"
    assert "payment" not in card and "session_id" not in str(card)


async def test_traveller_details_come_from_the_passport(client, user_token, llm, db_session):
    await upload(client, user_token, "passport.pdf", samples.pdf_bytes(samples.PASSPORT_TEXT))
    _, card = await search_and_propose_with_passport(client, user_token, llm)
    assert card["summary"]["travellers"] == ["ANNA MARIA ERIKSSON"]  # names only on screen
    row = await db_session.get(ConfirmationRequest, uuid.UUID(card["confirmation_id"]))
    assert row.params["travellers"] == [
        {"name": "ANNA MARIA ERIKSSON", "born_on": "1974-08-12", "gender": "f"}]


async def test_a_named_passport_holder_keeps_the_passport_details(client, user_token, llm,
                                                                  db_session):
    """Found live with Duffel: the model passed the passport name explicitly, which used to
    drop the date of birth and gender a real order needs."""
    await upload(client, user_token, "passport.pdf", samples.pdf_bytes(samples.PASSPORT_TEXT))
    _, card = await search_and_propose_with_passport(
        client, user_token, llm, travellers=["Anna Maria Eriksson", "Raj Mehta"])
    row = await db_session.get(ConfirmationRequest, uuid.UUID(card["confirmation_id"]))
    assert row.params["travellers"] == [
        {"name": "ANNA MARIA ERIKSSON", "born_on": "1974-08-12", "gender": "f"},
        {"name": "Raj Mehta"}]


async def search_and_propose_with_passport(client, token, llm, **book_args):
    llm.script(intent("flight"), call("search_flights", origin="BOM", destination="LHR",
                                      date=TRAVEL_DATE.isoformat()), "Options.")
    found = await ask(client, token, "Flights to London")
    offer_id = found["message"]["cards"][0]["offer_id"]
    llm.script(intent("flight"), call("book_flight", offer_id=offer_id, **book_args),
               "Confirm please.")
    proposed = await ask(client, token, "Book it", found["conversation_id"])
    return found["conversation_id"], proposed["message"]["cards"][0]
