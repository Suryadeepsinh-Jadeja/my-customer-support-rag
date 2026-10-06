"""The §84 demo end to end through the API, with the rule-based fake LLM (LLM_PROVIDER=fake):
upload → extraction → embeddings → answers with sources → book → confirm → cancel."""

import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import AuditLog, DocumentChunk
from app.rag.ingest import ingest
from app.services import jobs
from app.services.fake_llm import travel_date
from app.services.llm_service import get_llm
from tests import samples
from tests.conftest import bearer
from tests.test_chat import ask

KB_DIR = Path(__file__).resolve().parents[2] / "knowledge_base"


@pytest.fixture
def fake_llm(monkeypatch):
    monkeypatch.setattr(get_settings(), "LLM_PROVIDER", "fake")
    get_llm.cache_clear()
    yield
    get_llm.cache_clear()


def test_travel_dates_are_the_next_occurrence():
    today = date.today()
    later = today + timedelta(days=40)
    assert travel_date(f"to london for {later.strftime('%B').lower()} {later.day}") == later
    earlier = today - timedelta(days=40)
    parsed = travel_date(f"on {earlier.day} {earlier.strftime('%B')}")
    assert parsed is not None and parsed > today and parsed.month == earlier.month
    assert travel_date("next week") is None


async def test_demo_conversation(client, user_token, fake_llm, tmp_path, db_session):
    shutil.copytree(KB_DIR, tmp_path / "kb")
    await ingest(tmp_path / "kb")
    h = bearer(user_token)
    await client.patch("/api/users/me/profile", headers=h, json={"home_airport": "BOM"})

    # Upload and process three documents; chunks get (fake) embeddings.
    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    for name, data, ctype in [
        ("passport.pdf", samples.pdf_bytes(samples.PASSPORT_TEXT), "application/pdf"),
        ("ticket.pdf", samples.pdf_bytes(samples.FLIGHT_TICKET_TEXT), "application/pdf"),
        ("hotel.docx", samples.docx_bytes(samples.HOTEL_TEXT), docx),
    ]:
        assert (await client.post("/api/documents", headers=h,
                                  files={"file": (name, data, ctype)})).status_code == 202
    await jobs.run_pending()
    docs = (await client.get("/api/documents", headers=h)).json()
    assert {(d["filename"], d["status"]) for d in docs} == {
        ("passport.pdf", "ready"), ("ticket.pdf", "ready"), ("hotel.docx", "ready")}
    chunks = (await db_session.execute(select(DocumentChunk))).scalars().all()
    assert chunks and all(c.embedding for c in chunks)

    # Questions answered from the documents and the policy, with sources.
    body = await ask(client, user_token, "What is my flight number?")
    conversation = body["conversation_id"]
    assert body["agent"] == "flight" and body["message"]["type"] == "DOCUMENT_INFO"
    assert "LX154" in body["message"]["text"]
    assert {"type": "document", "title": "ticket.pdf"}.items() <= \
        body["message"]["sources"][0].items()

    body = await ask(client, user_token, "What time do I arrive?", conversation)
    assert "07:10" in body["message"]["text"] and "ZRH" in body["message"]["text"]

    body = await ask(client, user_token, "What is my baggage allowance?", conversation)
    assert "1 x 23 kg" in body["message"]["text"]
    assert "Baggage Policy" in {s["title"] for s in body["message"]["sources"]}

    # Book a flight: origin from the profile, offers as cards, confirmation required.
    day = date.today() + timedelta(days=30)
    when = f"{day.strftime('%B')} {day.day}"
    body = await ask(client, user_token, f"Book my flight to London for {when}", conversation)
    assert body["message"]["type"] == "FLIGHT_RESULTS"
    offers = [c for c in body["message"]["cards"] if c["type"] == "flight_offer"]
    assert len(offers) == 5
    assert {(o["origin"], o["destination"]) for o in offers} == {("BOM", "LHR")}
    assert all(o["start_date"] == day.isoformat() for o in offers)

    pick = offers[0]
    body = await ask(client, user_token, f"I'd like this one: {pick['title']} "
                                         f"(offer_id: {pick['offer_id']})", conversation)
    assert body["message"]["type"] == "CONFIRMATION_REQUEST"
    (card,) = [c for c in body["message"]["cards"] if c["type"] == "confirmation"]
    assert (await client.get("/api/bookings", headers=h)).json() == []

    booked = (await client.post("/api/chat/confirm", headers=h, json={
        "confirmation_id": card["confirmation_id"], "approved": True})).json()
    assert booked["message"]["type"] == "BOOKING_CONFIRMATION"
    assert booked["booking"]["status"] == "confirmed" and booked["booking"]["test_booking"]

    # Cancel: the provider's refund quote, then confirmation.
    body = await ask(client, user_token, "Cancel my flight", conversation)
    assert body["message"]["type"] == "CONFIRMATION_REQUEST"
    (card,) = [c for c in body["message"]["cards"] if c["type"] == "confirmation"]
    assert card["action"] == "cancel" and "refund_amount" in card["summary"]["refund"]
    cancelled = (await client.post("/api/chat/confirm", headers=h, json={
        "confirmation_id": card["confirmation_id"], "approved": True})).json()
    assert cancelled["booking"]["status"] == "cancelled"

    actions = list((await db_session.execute(
        select(AuditLog.action).where(AuditLog.action.like("booking.%"))
        .order_by(AuditLog.created_at))).scalars())
    assert actions == ["booking.book_requested", "booking.create",
                       "booking.cancel_requested", "booking.cancel"]


def test_fake_llm_is_refused_in_production(monkeypatch):
    from app.core.config import Settings

    with pytest.raises(ValueError, match="tests only"):
        Settings(APP_ENV="production", JWT_SECRET="x" * 40, STORAGE_ENCRYPTION_KEY="k",
                 LLM_PROVIDER="fake")
