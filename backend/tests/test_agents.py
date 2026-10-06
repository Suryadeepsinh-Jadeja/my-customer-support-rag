"""One scripted conversation per specialist agent (phase 5)."""

import shutil
from pathlib import Path

import pytest

from app.agents.prompts import SPECIALISTS
from app.rag.ingest import ingest
from tests import samples
from tests.fake_llm import call, intent
from tests.test_chat import ask, results, upload

KB_DIR = Path(__file__).resolve().parents[2] / "knowledge_base"


@pytest.fixture
async def kb(tmp_path):
    shutil.copytree(KB_DIR, tmp_path / "kb")
    await ingest(tmp_path / "kb")


def offered_tools(llm) -> set[str]:
    return {t.name for t in llm.calls[1][1]["tools"]}


def policies(found: dict) -> set[str]:
    return {r["policy"] for r in found["results"]}


async def test_flight_agent_explains_refunds_from_ticket_and_policy(client, user_token, llm, kb):
    await upload(client, user_token, "ticket.pdf", samples.pdf_bytes(samples.FLIGHT_TICKET_TEXT))
    llm.script(intent("flight", needs_documents=True, needs_policy=True),
               call("get_document_fields", document_type="flight_ticket"),
               call("search_policies", query="cancellation refund policy"),
               "Under the cancellation policy, your SWISS ticket LX154 ...")
    body = await ask(client, user_token, "Can I cancel my flight and get a refund?")

    assert body["agent"] == "flight"
    assert offered_tools(llm) == set(SPECIALISTS["flight"].tools)
    assert "check_travel_documents" in offered_tools(llm)
    system = llm.calls[1][1]["system"]
    assert "Give a refund or fee amount only if the policy or ticket states it" in system
    ticket, policy = results(llm)
    assert ticket["documents"][0]["document"] == "ticket.pdf"
    assert "Flight Cancellation and Refund Policy" in policies(policy)
    assert {s["type"] for s in body["message"]["sources"]} == {"document", "policy"}


async def test_hotel_agent_reads_the_hotel_booking(client, user_token, llm):
    await upload(client, user_token, "hotel.docx", samples.docx_bytes(samples.HOTEL_TEXT),
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    llm.script(intent("hotel", needs_documents=True),
               call("get_document_fields", document_type="hotel_booking"),
               call("list_documents"),  # not a hotel tool
               "Your confirmation number is HSP-99812.")
    body = await ask(client, user_token, "What's my hotel confirmation number?")

    assert body["agent"] == "hotel" and body["message"]["type"] == "DOCUMENT_INFO"
    fields, refused = results(llm)
    values = {f["field"]: f["value"] for f in fields["documents"][0]["fields"]}
    assert values["confirmation_number"] == "HSP-99812"
    assert refused == {"error": "There is no tool named 'list_documents'."}


@pytest.mark.parametrize(("domain", "query", "policy"), [
    ("car", "driving licence and deposit for a rental car", "Car Rental Policy"),
    ("excursion", "cancel an excursion", "Excursion and Trip Recommendation Policy"),
])
async def test_car_and_excursion_agents_use_their_policies(client, user_token, llm, kb,
                                                           domain, query, policy):
    llm.script(intent(domain, needs_policy=True), call("search_policies", query=query),
               "According to the policy ...")
    body = await ask(client, user_token, f"Question about {domain}")
    assert body["agent"] == domain
    assert offered_tools(llm) == set(SPECIALISTS[domain].tools)
    assert policy in policies(results(llm)[0])


async def test_document_agent_lists_documents_and_finds_conflicts(client, user_token, llm):
    await upload(client, user_token, "ticket.pdf", samples.pdf_bytes(samples.FLIGHT_TICKET_TEXT))
    await upload(client, user_token, "passport.pdf", samples.pdf_bytes(samples.PASSPORT_TEXT))
    llm.script(intent("document", needs_documents=True), call("list_documents"),
               call("check_travel_documents"),
               "You uploaded a ticket and a passport. Your passport expired in 2012 ...")
    body = await ask(client, user_token, "Show me my travel documents. Are they in order?")

    listed, checked = results(llm)
    assert {(d["document"], d["document_type"], d["status"]) for d in listed["documents"]} == {
        ("ticket.pdf", "flight_ticket", "ready"), ("passport.pdf", "passport", "ready")}
    issues = {(i["kind"], i["severity"]) for i in checked["issues"]}
    # The specimen passport (ERIKSSON ANNA MARIA, expired 2012) vs a ticket for ASHA MEHTA.
    assert issues == {("name_mismatch", "warning"), ("passport_expiry", "error")}
    assert {s["title"] for s in body["message"]["sources"]} == {"ticket.pdf", "passport.pdf"}


async def test_visa_questions_use_only_the_knowledge_base(client, user_token, llm, kb):
    llm.script(intent("document", needs_policy=True), call("get_user_profile"),
               call("search_policies", query="visa entry requirements travel documents"),
               "I can't confirm visa requirements; please check the embassy ...")
    body = await ask(client, user_token, "Do I need a visa for Switzerland?")

    system = llm.calls[1][1]["system"]
    assert "Never state visa rules from general knowledge" in system
    profile, found = results(llm)
    assert profile["full_name"] == "Ana Traveller"
    assert "Travel Documents and Special Assistance" in policies(found)
    assert body["message"]["sources"][0]["type"] == "policy"
