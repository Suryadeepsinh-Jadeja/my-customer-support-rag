"""HTTP API tests (FastAPI TestClient + scripted LLM)."""

import time

import pytest
from fastapi.testclient import TestClient

from customer_support_chat.app.api import create_app
from tests.conftest import BOOK_REF, PASSENGER, TICKET
from tests.fake_llm import reply, tool_call


@pytest.fixture
def client(service):
    return TestClient(create_app(service=service, warm_up=False), raise_server_exceptions=False)


def _login(client, passenger=PASSENGER, reference=BOOK_REF):
    response = client.post("/auth/login", json={"passenger_id": passenger, "booking_reference": reference})
    return response


def _auth(client):
    token = _login(client).json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


def test_login_success_and_masking(client):
    body = _login(client).json()
    assert body["session_token"]
    assert body["customer"] == "***333"


def test_login_accepts_ticket_number_and_lowercase_reference(client):
    assert _login(client, reference=TICKET).status_code == 200
    assert _login(client, reference=BOOK_REF.lower()).status_code == 200


def test_login_failure_is_clean(client):
    response = _login(client, reference="WRONG1")
    assert response.status_code == 401
    body = response.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "not_authenticated"
    assert "couldn't identify your customer account" in body["error"]["message"]
    assert "Traceback" not in response.text


def test_chat_policy_question_with_sources(client, scripted_llm):
    scripted_llm.script(tool_call("lookup_policy", query="baggage"), reply("One 23 kg bag."))
    response = client.post("/chat", json={"message": "What is the baggage policy?"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["response"] == "One 23 kg bag."
    assert body["agent"] == "Customer Support"
    assert body["sources"] and body["sources"][0]["document_name"]
    assert response.headers["X-Request-ID"]


def test_confirmation_flow_over_http(client, scripted_llm):
    headers = _auth(client)
    scripted_llm.script(
        tool_call("ToFlightBookingAssistant", request="change"),
        tool_call("update_ticket_to_new_flight", ticket_no=TICKET, new_flight_id=2),
    )
    pending = client.post("/chat", json={"message": "Change my flight"}, headers=headers).json()
    assert pending["status"] == "confirmation_required"
    assert pending["pending_actions"][0]["title"] == "Change your flight"

    scripted_llm.script(reply("Changed."))
    done = client.post(
        "/chat/confirm",
        json={"conversation_id": pending["conversation_id"], "approved": True},
        headers=headers,
    ).json()
    assert done["status"] == "success"
    assert done["response"] == "Changed."


def test_confirm_without_pending_action(client, scripted_llm):
    scripted_llm.script(reply("Hello!"))
    conversation_id = client.post("/chat", json={"message": "hi"}).json()["conversation_id"]
    response = client.post("/chat/confirm", json={"conversation_id": conversation_id, "approved": True})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_pending_action"


def test_conversation_is_bound_to_its_customer(client, scripted_llm):
    headers = _auth(client)
    scripted_llm.script(reply("Hi!"))
    conversation_id = client.post("/chat", json={"message": "hi"}, headers=headers).json()["conversation_id"]
    # A guest (or another customer) cannot continue it.
    response = client.post("/chat", json={"conversation_id": conversation_id, "message": "show my flight"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "conversation_not_found"


@pytest.mark.parametrize(
    "payload",
    [{"message": ""}, {"message": "   "}, {"message": "x" * 2001}, {"message": "hi", "conversation_id": "not-a-uuid"}],
)
def test_invalid_input_rejected(client, payload):
    response = client.post("/chat", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_bad_token_rejected(client):
    response = client.post("/chat", json={"message": "hi"}, headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_llm_failure_is_reported_cleanly(client, scripted_llm):
    def boom(messages):
        raise RuntimeError("upstream 500 with secret details")

    scripted_llm.script(boom)
    response = client.post("/chat", json={"message": "hello"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "assistant_unavailable"
    assert "secret details" not in response.text


def test_rate_limit_is_reported_as_busy(client, scripted_llm):
    class GoogleRateLimitError(Exception):
        pass

    def limited(messages):
        raise GoogleRateLimitError("429 RESOURCE_EXHAUSTED quota")

    scripted_llm.script(limited)
    response = client.post("/chat", json={"message": "hello"})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"


def test_timeout(client, scripted_llm, monkeypatch):
    from customer_support_chat.app import api

    monkeypatch.setattr(api.settings, "REQUEST_TIMEOUT_SECONDS", 0.2)

    def slow(messages):
        time.sleep(1)
        return reply("too late")

    scripted_llm.script(slow)
    response = client.post("/chat", json={"message": "hello"})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "timeout"


def test_health_reports_missing_llm_key(client):
    response = client.get("/health")
    body = response.json()
    assert body["checks"]["database"] is True
    assert body["checks"]["knowledge_base"] is True
    assert body["checks"]["llm_configured"] is False
    assert body["status"] == "degraded"
