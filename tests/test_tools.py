"""Tool tests against the fixture database."""

import sqlite3
from contextlib import closing

import pytest

from customer_support_chat.app.core.errors import CustomerNotIdentifiedError
from customer_support_chat.app.services.tools import (
    book_car_rental,
    book_excursion,
    book_hotel,
    cancel_car_rental,
    cancel_hotel,
    cancel_ticket,
    fetch_user_flight_information,
    search_car_rentals,
    search_flights,
    search_hotels,
    update_car_rental,
    update_excursion,
    update_hotel,
    update_ticket_to_new_flight,
)
from tests.conftest import OTHER_TICKET, PASSENGER, TICKET

SIGNED_IN = {"configurable": {"passenger_id": PASSENGER}}


def _one(db, sql, *params):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute(sql, params).fetchone()


# ------------------------------------------------------------------ flights


def test_fetch_user_flights_requires_identity(db):
    with pytest.raises(CustomerNotIdentifiedError):
        fetch_user_flight_information.invoke({}, config={"configurable": {}})


def test_fetch_user_flights(db):
    flights = fetch_user_flight_information.invoke({}, config=SIGNED_IN)
    assert len(flights) == 1
    assert flights[0]["ticket_no"] == TICKET
    assert flights[0]["seat_no"] == "12A"
    assert flights[0]["fare_conditions"] == "Economy"


def test_search_flights_structured(db):
    results = search_flights.invoke({"departure_airport": "bsl", "arrival_airport": "CDG"})
    assert [f["flight_no"] for f in results] == ["LX0116", "LX0112", "LX0114"]


def test_search_flights_date_window(db):
    from datetime import date, timedelta

    day = (date.today() + timedelta(days=9)).isoformat()
    results = search_flights.invoke({"start_time": day, "end_time": day})
    assert [f["flight_no"] for f in results] == ["LX0200"]


def test_update_ticket_to_new_flight(db):
    msg = update_ticket_to_new_flight.invoke({"ticket_no": TICKET, "new_flight_id": 2}, config=SIGNED_IN)
    assert "successfully updated" in msg
    assert _one(db, "SELECT flight_id FROM ticket_flights WHERE ticket_no = ?", TICKET)[0] == 2


def test_update_ticket_rejects_flight_departing_too_soon(db):
    msg = update_ticket_to_new_flight.invoke({"ticket_no": TICKET, "new_flight_id": 3}, config=SIGNED_IN)
    assert "Not permitted" in msg
    assert _one(db, "SELECT flight_id FROM ticket_flights WHERE ticket_no = ?", TICKET)[0] == 1


def test_update_ticket_rejects_unknown_flight(db):
    msg = update_ticket_to_new_flight.invoke({"ticket_no": TICKET, "new_flight_id": 999}, config=SIGNED_IN)
    assert "Invalid new flight" in msg


def test_cannot_update_someone_elses_ticket(db):
    msg = update_ticket_to_new_flight.invoke({"ticket_no": OTHER_TICKET, "new_flight_id": 2}, config=SIGNED_IN)
    assert "not found" in msg
    assert _one(db, "SELECT flight_id FROM ticket_flights WHERE ticket_no = ?", OTHER_TICKET)[0] == 4


def test_cancel_ticket(db):
    assert "successfully cancelled" in cancel_ticket.invoke({"ticket_no": TICKET}, config=SIGNED_IN)
    assert _one(db, "SELECT 1 FROM tickets WHERE ticket_no = ?", TICKET) is None


def test_cancel_ticket_requires_identity(db):
    with pytest.raises(CustomerNotIdentifiedError):
        cancel_ticket.invoke({"ticket_no": TICKET}, config={"configurable": {}})


# ------------------------------------------------------- hotels / cars / trips


def test_hotel_search_book_update_cancel(db, vector_store):
    hits = search_hotels.invoke({"query": "luxury hotel in Basel"})
    assert hits[0]["name"] == "Hilton Basel"

    assert "successfully booked" in book_hotel.invoke({"hotel_id": 1})
    assert _one(db, "SELECT booked FROM hotels WHERE id = 1")[0] == 1

    assert "successfully updated" in update_hotel.invoke({"hotel_id": 1, "checkin_date": "2026-10-12"})
    assert _one(db, "SELECT checkin_date FROM hotels WHERE id = 1")[0] == "2026-10-12"
    assert "Nothing to update" in update_hotel.invoke({"hotel_id": 1})
    assert "No hotel found" in update_hotel.invoke({"hotel_id": 99, "checkin_date": "2026-10-12"})

    assert "successfully cancelled" in cancel_hotel.invoke({"hotel_id": 1})
    assert _one(db, "SELECT booked FROM hotels WHERE id = 1")[0] == 0


def test_car_rental_search_book_update_cancel(db, vector_store):
    hits = search_car_rentals.invoke({"query": "economy car Basel"})
    assert hits[0]["location"] == "Basel"
    assert "successfully booked" in book_car_rental.invoke({"rental_id": 1})
    assert "successfully updated" in update_car_rental.invoke({"rental_id": 1, "end_date": "2026-10-15"})
    assert _one(db, "SELECT end_date FROM car_rentals WHERE id = 1")[0] == "2026-10-15"
    assert "successfully cancelled" in cancel_car_rental.invoke({"rental_id": 1})
    assert "No car rental found" in book_car_rental.invoke({"rental_id": 42})


def test_excursion_book_and_update(db):
    assert "successfully booked" in book_excursion.invoke({"recommendation_id": 1})
    assert "successfully updated" in update_excursion.invoke({"recommendation_id": 1, "details": "Group of 4"})
    assert _one(db, "SELECT details FROM trip_recommendations WHERE id = 1")[0] == "Group of 4"
