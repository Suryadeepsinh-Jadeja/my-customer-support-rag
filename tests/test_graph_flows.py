"""Graph-level tests with a scripted LLM and real tools / RAG / database."""

import sqlite3
from contextlib import closing

from langchain_core.messages import ToolMessage

from tests.conftest import BOOK_REF, OTHER_TICKET, PASSENGER, TICKET
from tests.fake_llm import reply, tool_call


def _signed_in(service):
    return service.authenticate(PASSENGER, BOOK_REF)


def _tool_messages(messages, name):
    return [m for m in messages if isinstance(m, ToolMessage) and m.name == name]


# --------------------------------------------------------------------- RAG


def test_policy_question_uses_rag_and_returns_sources(service, scripted_llm):
    def answer_from_context(messages):
        tool_result = _tool_messages(messages, "lookup_policy")[-1].content
        assert "Baggage Policy" in tool_result
        return reply("Economy Classic includes 1 checked bag of 23 kg (Baggage Policy).")

    scripted_llm.script(tool_call("lookup_policy", query="baggage allowance"), answer_from_context)

    result = service.chat("What is the baggage policy?", session=_signed_in(service))

    assert result.status == "success"
    assert result.agent == "Customer Support"
    assert "23 kg" in result.response
    assert result.sources, "RAG answers must carry sources"
    assert any(s["document_name"] == "Baggage Policy" for s in result.sources)
    assert {"document_name", "section", "source", "chunk_id", "score"} <= set(result.sources[0])


def test_unknown_policy_is_not_invented(service, scripted_llm):
    def check(messages):
        assert "NO_RELEVANT_POLICY_FOUND" in _tool_messages(messages, "lookup_policy")[-1].content
        return reply("I couldn't verify that in our official policies.")

    scripted_llm.script(tool_call("lookup_policy", query="emotional support peacock"), check)
    result = service.chat("Can I fly with my emotional support peacock?")
    assert result.sources == []
    assert "couldn't verify" in result.response


def test_hybrid_policy_plus_customer_booking(service, scripted_llm):
    """'Can I cancel and what refund?' needs the customer's fare (booking data) AND policy (RAG)."""

    def combine(messages):
        system = messages[0].content
        assert "Fare Class: Economy" in system  # customer-specific data, from the database
        assert "Cancellation" in _tool_messages(messages, "lookup_policy")[-1].content  # policy, from RAG
        return reply("Your Economy ticket is refundable minus CHF 150 (Flight Cancellation and Refund Policy).")

    scripted_llm.script(tool_call("lookup_policy", query="cancellation refund economy"), combine)
    result = service.chat("Can I cancel my flight, and what refund will I get?", session=_signed_in(service))
    assert any("Cancellation" in s["document_name"] for s in result.sources)
    assert "CHF 150" in result.response


# ------------------------------------------------------------------ routing


def test_primary_routes_to_flight_assistant(service, scripted_llm):
    scripted_llm.script(
        tool_call("ToFlightBookingAssistant", request="show flight details"),
        tool_call("fetch_user_flight_information"),
        lambda m: reply(f"Your flight is LX0112, seat 12A.") if "LX0112" in _tool_messages(m, "fetch_user_flight_information")[-1].content else reply("missing"),
    )
    result = service.chat("Show me my flight information.", session=_signed_in(service))
    assert result.agent == "Flight Support"
    assert result.response == "Your flight is LX0112, seat 12A."


def test_follow_up_message_goes_straight_to_active_specialist(service, scripted_llm):
    session = _signed_in(service)
    scripted_llm.script(
        tool_call("ToHotelBookingAssistant", request="book a hotel"),
        reply("Which city do you need a hotel in?"),
    )
    first = service.chat("I want to book a hotel.", session=session)
    assert first.agent == "Hotel Support"

    calls_before = len(scripted_llm.calls)
    scripted_llm.script(reply("Here are hotels in Basel."))
    second = service.chat("Basel please", conversation_id=first.conversation_id, session=session)
    assert second.agent == "Hotel Support"
    # Exactly one model call: the hotel assistant, without going through the primary assistant.
    assert len(scripted_llm.calls) == calls_before + 1
    assert "hotel bookings" in scripted_llm.calls[-1][0].content


def test_complete_or_escalate_returns_to_primary(service, scripted_llm):
    session = _signed_in(service)
    scripted_llm.script(
        tool_call("ToBookCarRental", request="car"),
        tool_call("CompleteOrEscalate", reason="User asked about baggage instead"),
        reply("Sure, what would you like to know about baggage?"),
    )
    result = service.chat("I need a rental car... actually never mind", session=session)
    assert result.agent == "Customer Support"
    state = service.graph.get_state(service._config(result.conversation_id, PASSENGER)).values
    assert state["dialog_state"] == []
    # Every tool call (incl. CompleteOrEscalate) got a matching tool response.
    call_ids = {tc["id"] for m in state["messages"] for tc in getattr(m, "tool_calls", []) or []}
    answered = {m.tool_call_id for m in state["messages"] if isinstance(m, ToolMessage)}
    assert call_ids <= answered


# ------------------------------------------- sensitive actions & confirmation


def _ticket_flight(db, ticket):
    with closing(sqlite3.connect(db)) as conn:
        row = conn.execute("SELECT flight_id FROM ticket_flights WHERE ticket_no = ?", (ticket,)).fetchone()
    return row[0] if row else None


def test_flight_change_requires_confirmation_then_executes(service, scripted_llm, db):
    session = _signed_in(service)
    scripted_llm.script(
        tool_call("ToFlightBookingAssistant", request="change flight"),
        tool_call("search_flights", departure_airport="BSL", arrival_airport="CDG"),
        tool_call("update_ticket_to_new_flight", ticket_no=TICKET, new_flight_id=2),
    )
    pending = service.chat("I want to change my flight to the next day.", session=session)

    assert pending.status == "confirmation_required"
    assert pending.pending_actions[0].title == "Change your flight"
    assert any("LX0114" in d["value"] for d in pending.pending_actions[0].details)
    assert _ticket_flight(db, TICKET) == 1, "nothing may change before confirmation"

    scripted_llm.script(reply("Done - you are now on LX0114."))
    done = service.confirm(pending.conversation_id, approved=True, session=session)
    assert done.status == "success"
    assert _ticket_flight(db, TICKET) == 2
    assert done.response == "Done - you are now on LX0114."


def test_declined_action_is_not_executed(service, scripted_llm, db):
    session = _signed_in(service)
    scripted_llm.script(
        tool_call("ToFlightBookingAssistant", request="cancel"),
        tool_call("cancel_ticket", ticket_no=TICKET),
    )
    pending = service.chat("Cancel my flight.", session=session)
    assert pending.status == "confirmation_required"

    def acknowledge(messages):
        assert "denied by user" in messages[-1].content
        return reply("Okay, I have not cancelled anything.")

    scripted_llm.script(acknowledge)
    result = service.confirm(pending.conversation_id, approved=False, reason="changed my mind", session=session)
    assert result.status == "success"
    assert _ticket_flight(db, TICKET) == 1


def test_new_message_while_pending_counts_as_decline(service, scripted_llm, db):
    session = _signed_in(service)
    scripted_llm.script(
        tool_call("ToFlightBookingAssistant", request="cancel"),
        tool_call("cancel_ticket", ticket_no=TICKET),
    )
    pending = service.chat("Cancel my flight.", session=session)
    scripted_llm.script(lambda m: reply("Understood, keeping your ticket.") if "wait" in m[-1].content else reply("?"))
    result = service.chat("wait, don't", conversation_id=pending.conversation_id, session=session)
    assert result.status == "success"
    assert _ticket_flight(db, TICKET) == 1


def _booked(db, table, row_id):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute(f"SELECT booked FROM {table} WHERE id = ?", (row_id,)).fetchone()[0]


def test_car_rental_flow(service, scripted_llm, db):
    session = _signed_in(service)
    scripted_llm.script(
        tool_call("ToBookCarRental", request="car in Basel", location="Basel"),
        tool_call("search_car_rentals", query="economy car Basel"),
        tool_call("book_car_rental", rental_id=1),
    )
    pending = service.chat("I need a rental car in Basel.", session=session)
    assert pending.agent == "Car Rental Support"
    assert pending.pending_actions[0].title == "Book a car rental"
    assert _booked(db, "car_rentals", 1) == 0
    scripted_llm.script(reply("Your Europcar rental is booked."))
    service.confirm(pending.conversation_id, approved=True, session=session)
    assert _booked(db, "car_rentals", 1) == 1


def test_hotel_flow(service, scripted_llm, db):
    session = _signed_in(service)
    scripted_llm.script(
        tool_call("ToHotelBookingAssistant", request="hotel", location="Basel"),
        tool_call("search_hotels", query="luxury hotel Basel"),
        tool_call("book_hotel", hotel_id=1),
    )
    pending = service.chat("I want to book a hotel in Basel.", session=session)
    assert pending.agent == "Hotel Support"
    assert any("Hilton Basel" in d["value"] for d in pending.pending_actions[0].details)
    scripted_llm.script(reply("Hilton Basel is booked."))
    service.confirm(pending.conversation_id, approved=True, session=session)
    assert _booked(db, "hotels", 1) == 1


def test_excursion_flow(service, scripted_llm, db):
    session = _signed_in(service)

    def recommend(messages):
        results = _tool_messages(messages, "search_trip_recommendations")[-1].content
        assert "Louvre" in results or "Basel Minster" in results
        return tool_call("book_excursion", recommendation_id=2)

    scripted_llm.script(
        tool_call("ToBookExcursion", request="art", location="Paris"),
        tool_call("search_trip_recommendations", query="art museum Paris"),
        recommend,
    )
    pending = service.chat("Recommend an excursion for my trip.", session=session)
    assert pending.agent == "Trips & Excursions"
    scripted_llm.script(reply("Louvre booked."))
    service.confirm(pending.conversation_id, approved=True, session=session)
    assert _booked(db, "trip_recommendations", 2) == 1


def test_cannot_touch_another_customers_ticket(service, scripted_llm, db):
    session = _signed_in(service)
    scripted_llm.script(
        tool_call("ToFlightBookingAssistant", request="cancel"),
        tool_call("cancel_ticket", ticket_no=OTHER_TICKET),
    )
    pending = service.chat("Cancel ticket 7240000000000002", session=session)

    def check(messages):
        assert "was not found in the signed-in customer's bookings" in messages[-1].content
        return reply("I couldn't find that ticket in your bookings.")

    scripted_llm.script(check)
    service.confirm(pending.conversation_id, approved=True, session=session)
    assert _ticket_flight(db, OTHER_TICKET) == 4


# -------------------------------------------------------------------- guest


def test_guest_gets_sign_in_prompt_for_booking_data(service, scripted_llm):
    def check(messages):
        assert "not signed in" in messages[0].content
        return reply("Please sign in so I can look up your booking.")

    scripted_llm.script(check)
    result = service.chat("Show me my flight")
    assert "sign in" in result.response
