"""Unit tests: state, routing, assistant base, utilities, configuration."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate

from customer_support_chat.app.core.errors import ConfigurationError
from customer_support_chat.app.core.state import update_dialog_stack
from customer_support_chat.app.graph import (
    _specialist_router,
    pop_dialog_state,
    route_primary_assistant,
    route_to_workflow,
)
from customer_support_chat.app.services.assistants.assistant_base import Assistant, _has_text
from customer_support_chat.app.services.assistants.flight_booking_assistant import update_flight_safe_tools
from customer_support_chat.app.services.utils import flight_info_to_string
from tests.fake_llm import ScriptedChatModel, reply, tool_call


def _prompted(llm):
    return ChatPromptTemplate.from_messages([("placeholder", "{messages}")]) | llm


def _state(*messages, dialog_state=None):
    return {"messages": list(messages), "dialog_state": dialog_state or [], "user_info": ""}


# -------------------------------------------------------------------- state


def test_dialog_stack_push_pop_noop():
    assert update_dialog_stack([], "book_hotel") == ["book_hotel"]
    assert update_dialog_stack(["book_hotel"], "pop") == []
    assert update_dialog_stack(["book_hotel"], None) == ["book_hotel"]


# ------------------------------------------------------------------ routing


@pytest.mark.parametrize(
    "tool,expected",
    [
        ("ToFlightBookingAssistant", "enter_update_flight"),
        ("ToBookCarRental", "enter_book_car_rental"),
        ("ToHotelBookingAssistant", "enter_book_hotel"),
        ("ToBookExcursion", "enter_book_excursion"),
        ("lookup_policy", "primary_assistant_tools"),
    ],
)
def test_primary_routing(tool, expected):
    assert route_primary_assistant(_state(tool_call(tool, request="x"))) == expected


def test_primary_routing_ends_on_plain_reply():
    assert route_primary_assistant(_state(reply("hello"))) == "__end__"


def test_route_to_workflow_resumes_active_assistant():
    assert route_to_workflow(_state()) == "primary_assistant"
    assert route_to_workflow(_state(dialog_state=["book_hotel"])) == "book_hotel"


def test_specialist_routing_safe_sensitive_escalate():
    route = _specialist_router("update_flight", update_flight_safe_tools)
    assert route(_state(tool_call("search_flights"))) == "update_flight_safe_tools"
    assert route(_state(tool_call("lookup_policy", query="x"))) == "update_flight_safe_tools"
    assert route(_state(tool_call("cancel_ticket", ticket_no="1"))) == "update_flight_sensitive_tools"
    assert route(_state(tool_call("CompleteOrEscalate", reason="done"))) == "leave_skill"
    assert route(_state(reply("ok"))) == "__end__"


def test_mixed_safe_and_sensitive_calls_require_confirmation():
    route = _specialist_router("update_flight", update_flight_safe_tools)
    message = AIMessage(
        content="",
        tool_calls=[
            {"name": "search_flights", "args": {}, "id": "a"},
            {"name": "cancel_ticket", "args": {"ticket_no": "1"}, "id": "b"},
        ],
    )
    assert route(_state(message)) == "update_flight_sensitive_tools"


def test_pop_dialog_state_answers_every_tool_call():
    message = AIMessage(
        content="",
        tool_calls=[{"name": "CompleteOrEscalate", "args": {"reason": "x"}, "id": "c1"}],
    )
    update = pop_dialog_state(_state(message, dialog_state=["book_hotel"]))
    assert update["dialog_state"] == "pop"
    assert [m.tool_call_id for m in update["messages"]] == ["c1"]


# ---------------------------------------------------------------- assistant


def test_assistant_retries_empty_response_then_succeeds():
    llm = ScriptedChatModel().script(reply(""), reply("Real answer"))
    result = Assistant(_prompted(llm)).invoke(_state(HumanMessage(content="hi")))
    assert result["messages"].content == "Real answer"


def test_assistant_gives_up_after_bounded_retries():
    llm = ScriptedChatModel().script(reply(""), reply(""), reply(""), reply("never reached"))
    result = Assistant(_prompted(llm)).invoke(_state(HumanMessage(content="hi")))
    assert result["messages"].content == ""
    assert llm.remaining == 1


def test_has_text_handles_content_parts():
    assert _has_text([{"type": "text", "text": "hi"}])
    assert not _has_text([{"type": "text", "text": " "}])
    assert not _has_text("")


def test_missing_api_key_is_a_configuration_error(monkeypatch):
    from customer_support_chat.app.services.assistants import assistant_base

    monkeypatch.setattr(assistant_base, "_llm", None)
    monkeypatch.setattr(assistant_base.get_settings(), "GEMINI_API_KEY", "")
    with pytest.raises(ConfigurationError):
        assistant_base.get_llm()


# -------------------------------------------------------------------- utils


def test_flight_info_to_string_is_readable():
    text = flight_info_to_string(
        [
            {
                "ticket_no": "T1", "book_ref": "B1", "flight_id": 1, "flight_no": "LX1",
                "departure_airport": "BSL", "arrival_airport": "CDG",
                "scheduled_departure": "2026-10-10 10:00", "scheduled_arrival": "2026-10-10 11:00",
                "seat_no": "12A", "fare_conditions": "Economy",
            }
        ]
    )
    assert "Ticket Number: T1\n" in text
    assert "Fare Class: Economy" in text


def test_tracing_is_off_without_key(monkeypatch):
    from customer_support_chat.app.core.settings import Config, configure_tracing

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    assert configure_tracing(Config()) is False
    import os

    assert os.environ["LANGSMITH_TRACING"] == "false"


def test_mask_id_hides_customer_identifiers():
    from customer_support_chat.app.core.logger import mask_id

    assert mask_id("8149 604011") == "***011"
    assert mask_id(None) == "-"
