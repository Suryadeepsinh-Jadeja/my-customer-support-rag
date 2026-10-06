from vectorizer.app.vectordb.vectordb import VectorDB
from customer_support_chat.app.core.settings import get_settings
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
import secrets
import sqlite3
from contextlib import closing
from typing import Optional, Union, List, Dict
from datetime import datetime, date, timedelta
import pytz

from customer_support_chat.app.core.errors import CustomerNotIdentifiedError

settings = get_settings()
db = settings.SQLITE_DB_PATH
flights_vectordb = VectorDB(table_name="flights", collection_name="flights_collection")

# Flight changes are only allowed up to this long before departure (see flight_change_policy.md).
MIN_HOURS_BEFORE_DEPARTURE = 3


def get_passenger_id(config: RunnableConfig) -> str:
    """The authenticated customer's passenger id, injected by the API per request."""
    passenger_id = (config or {}).get("configurable", {}).get("passenger_id")
    if not passenger_id:
        raise CustomerNotIdentifiedError(
            "The customer is not signed in, so no booking data is available. "
            "Ask the customer to sign in with their passenger ID and booking reference."
        )
    return passenger_id


@tool
def fetch_user_flight_information(*, config: RunnableConfig) -> List[Dict]:
    """Fetch all tickets for the user along with corresponding flight information and seat assignments."""
    passenger_id = get_passenger_id(config)

    query = """
    SELECT 
        t.ticket_no, t.book_ref,
        f.flight_id, f.flight_no, f.departure_airport, f.arrival_airport, f.scheduled_departure, f.scheduled_arrival,
        bp.seat_no, tf.fare_conditions
    FROM 
        tickets t
        JOIN ticket_flights tf ON t.ticket_no = tf.ticket_no
        JOIN flights f ON tf.flight_id = f.flight_id
        LEFT JOIN boarding_passes bp ON bp.ticket_no = t.ticket_no AND bp.flight_id = f.flight_id
    WHERE 
        t.passenger_id = ?
    """
    with closing(sqlite3.connect(db)) as conn:
        cursor = conn.execute(query, (passenger_id,))
        column_names = [column[0] for column in cursor.description]
        return [dict(zip(column_names, row)) for row in cursor.fetchall()]

@tool
def search_flights(
    departure_airport: Optional[str] = None,
    arrival_airport: Optional[str] = None,
    start_time: Optional[date] = None,
    end_time: Optional[date] = None,
    query: Optional[str] = None,
    limit: int = 10,
) -> List[Dict]:
    """Search the flight schedule. Prefer the structured filters: departure_airport and
    arrival_airport are 3-letter IATA codes (e.g. "BSL", "CDG"); start_time/end_time are
    YYYY-MM-DD dates bounding the scheduled departure. Use `query` only for free-text
    searches when no filters apply. Returns flight_id values usable for rebooking."""
    if departure_airport or arrival_airport or start_time or end_time:
        sql = (
            "SELECT flight_id, flight_no, departure_airport, arrival_airport, "
            "scheduled_departure, scheduled_arrival, status, aircraft_code "
            "FROM flights WHERE 1 = 1"
        )
        params: list = []
        if departure_airport:
            sql += " AND departure_airport = ?"
            params.append(departure_airport.strip().upper())
        if arrival_airport:
            sql += " AND arrival_airport = ?"
            params.append(arrival_airport.strip().upper())
        if start_time:
            sql += " AND scheduled_departure >= ?"
            params.append(start_time.isoformat())
        if end_time:
            # Include the whole end day.
            sql += " AND scheduled_departure < ?"
            params.append((end_time + timedelta(days=1)).isoformat())
        sql += " ORDER BY scheduled_departure LIMIT ?"
        params.append(max(1, min(limit, 20)))
        with closing(sqlite3.connect(db)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    if not query:
        return []

    search_results = flights_vectordb.search(query, limit=min(limit, 5))

    flights = []
    for result in search_results:
        payload = result.payload
        flights.append({
            "flight_id": payload["flight_id"],
            "flight_no": payload["flight_no"],
            "departure_airport": payload["departure_airport"],
            "arrival_airport": payload["arrival_airport"],
            "scheduled_departure": payload["scheduled_departure"],
            "scheduled_arrival": payload["scheduled_arrival"],
            "status": payload["status"],
            "aircraft_code": payload["aircraft_code"],
            "actual_departure": payload["actual_departure"],
            "actual_arrival": payload["actual_arrival"],
            "chunk": payload["content"],
            "similarity": result.score,
        })
    return flights

def _hours_until(scheduled_departure) -> float:
    departure = datetime.fromisoformat(str(scheduled_departure))
    if departure.tzinfo is None:
        departure = departure.replace(tzinfo=pytz.UTC)
    return (departure - datetime.now(pytz.UTC)).total_seconds() / 3600


@tool
def update_ticket_to_new_flight(
    ticket_no: str,
    new_flight_id: int,
    old_flight_id: Optional[int] = None,
    *,
    config: RunnableConfig,
) -> str:
    """Move one flight of the user's ticket to a new flight on the same route (use the
    flight_id returned by search_flights). If the ticket has several flights, set
    old_flight_id to the flight_id being replaced. Origin and destination cannot change."""
    passenger_id = get_passenger_id(config)

    with closing(sqlite3.connect(db)) as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT departure_airport, arrival_airport, scheduled_departure FROM flights WHERE flight_id = ?",
            (new_flight_id,),
        )
        new_flight = cursor.fetchone()
        if not new_flight:
            return f"Invalid new flight ID {new_flight_id} provided."

        if _hours_until(new_flight[2]) < MIN_HOURS_BEFORE_DEPARTURE:
            return (
                f"Not permitted to reschedule to flight {new_flight_id}: it departs in less than "
                f"{MIN_HOURS_BEFORE_DEPARTURE} hours (scheduled {new_flight[2]})."
            )

        # Check if the ticket exists and belongs to the passenger
        cursor.execute(
            "SELECT 1 FROM tickets WHERE ticket_no = ? AND passenger_id = ?",
            (ticket_no, passenger_id),
        )
        if not cursor.fetchone():
            return f"Ticket {ticket_no} was not found in the signed-in customer's bookings."

        cursor.execute(
            """
            SELECT tf.flight_id, f.departure_airport, f.arrival_airport, f.scheduled_departure
            FROM ticket_flights tf JOIN flights f ON tf.flight_id = f.flight_id
            WHERE tf.ticket_no = ?
            ORDER BY f.scheduled_departure
            """,
            (ticket_no,),
        )
        legs = cursor.fetchall()
        if old_flight_id is not None:
            matching = [leg for leg in legs if leg[0] == old_flight_id]
            if not matching:
                return f"Flight {old_flight_id} is not part of ticket {ticket_no}."
            old_leg = matching[0]
        elif len(legs) == 1:
            old_leg = legs[0]
        elif not legs:
            return f"Ticket {ticket_no} has no flights to change."
        else:
            options = ", ".join(f"{leg[0]} ({leg[1]} -> {leg[2]})" for leg in legs)
            return (
                f"Ticket {ticket_no} has {len(legs)} flights: {options}. "
                "Ask the customer which one to change and pass its flight_id as old_flight_id."
            )

        old_id, old_from, old_to, old_departure = old_leg
        if new_flight_id == old_id:
            return f"Ticket {ticket_no} is already on flight {new_flight_id}."
        if (new_flight[0], new_flight[1]) != (old_from, old_to):
            return (
                f"Not permitted: flight {new_flight_id} flies {new_flight[0]} -> {new_flight[1]}, but the "
                f"flight being changed flies {old_from} -> {old_to}. Origin and destination cannot be "
                "changed; that requires cancelling and booking a new flight."
            )
        if _hours_until(old_departure) < MIN_HOURS_BEFORE_DEPARTURE:
            return (
                f"Not permitted to change flight {old_id}: changes are only possible up to "
                f"{MIN_HOURS_BEFORE_DEPARTURE} hours before its departure (scheduled {old_departure})."
            )

        cursor.execute(
            "UPDATE ticket_flights SET flight_id = ? WHERE ticket_no = ? AND flight_id = ?",
            (new_flight_id, ticket_no, old_id),
        )
        # The seat on the old flight does not carry over to the new one.
        cursor.execute(
            "DELETE FROM boarding_passes WHERE ticket_no = ? AND flight_id = ?",
            (ticket_no, old_id),
        )
        conn.commit()

    return (
        f"Ticket {ticket_no} successfully updated from flight {old_id} to flight {new_flight_id}. "
        "The previous seat assignment does not carry over."
    )


@tool
def cancel_ticket(ticket_no: str, *, config: RunnableConfig) -> str:
    """Cancel the user's ticket and remove it from the database."""
    passenger_id = get_passenger_id(config)

    with closing(sqlite3.connect(db)) as conn:
        cursor = conn.cursor()

        # Check if the ticket exists and belongs to the passenger
        cursor.execute(
            "SELECT 1 FROM tickets WHERE ticket_no = ? AND passenger_id = ?",
            (ticket_no, passenger_id),
        )
        if not cursor.fetchone():
            return f"Ticket {ticket_no} was not found in the signed-in customer's bookings."

        for table in ("boarding_passes", "ticket_flights", "tickets"):
            cursor.execute(f"DELETE FROM {table} WHERE ticket_no = ?", (ticket_no,))
        conn.commit()

    return f"Ticket {ticket_no} successfully cancelled."

@tool
def book_flight(
    flight_id: int,
    fare_conditions: str = "Economy",
    *,
    config: RunnableConfig
) -> str:
    """Book a selected flight for the configured passenger."""

    passenger_id = get_passenger_id(config)

    conn = sqlite3.connect(db)
    cursor = conn.cursor()

    try:
        # -------------------------------------------------
        # 1. Check passenger exists
        # -------------------------------------------------
        cursor.execute(
            """
            SELECT ticket_no
            FROM tickets
            WHERE passenger_id = ?
            LIMIT 1
            """,
            (passenger_id,)
        )

        passenger_ticket = cursor.fetchone()

        if not passenger_ticket:
            return f"Passenger {passenger_id} was not found."

        # -------------------------------------------------
        # 2. Check flight exists
        # -------------------------------------------------
        cursor.execute(
            """
            SELECT
                flight_id,
                flight_no,
                departure_airport,
                arrival_airport,
                scheduled_departure
            FROM flights
            WHERE flight_id = ?
            """,
            (flight_id,)
        )

        flight = cursor.fetchone()

        if not flight:
            return f"Flight {flight_id} does not exist."

        if _hours_until(flight[4]) < MIN_HOURS_BEFORE_DEPARTURE:
            return (
                f"Flight {flight_id} cannot be booked: it departs in less than "
                f"{MIN_HOURS_BEFORE_DEPARTURE} hours (scheduled {flight[4]})."
            )

        # -------------------------------------------------
        # 3. Find valid fare for this flight
        # -------------------------------------------------
        cursor.execute(
            """
            SELECT amount
            FROM ticket_flights
            WHERE flight_id = ?
              AND fare_conditions = ?
            LIMIT 1
            """,
            (flight_id, fare_conditions)
        )

        fare = cursor.fetchone()

        if not fare:
            return (
                f"Fare '{fare_conditions}' is not available "
                f"for flight {flight_id}."
            )

        amount = fare[0]

        # -------------------------------------------------
        # 4. Check duplicate booking
        # -------------------------------------------------
        cursor.execute(
            """
            SELECT t.ticket_no
            FROM tickets t
            JOIN ticket_flights tf
                ON t.ticket_no = tf.ticket_no
            WHERE t.passenger_id = ?
              AND tf.flight_id = ?
            """,
            (passenger_id, flight_id)
        )

        duplicate = cursor.fetchone()

        if duplicate:
            return (
                f"Passenger {passenger_id} is already booked "
                f"on flight {flight_id}."
            )

        # -------------------------------------------------
        # 5. Generate a booking reference not used yet
        # -------------------------------------------------
        # Existing references are not sequential, so "last + 1" can collide.
        while True:
            book_ref = secrets.token_hex(3).upper()
            cursor.execute("SELECT 1 FROM bookings WHERE book_ref = ?", (book_ref,))
            if not cursor.fetchone():
                break

        # -------------------------------------------------
        # 6. Generate ticket number (one above the highest)
        # -------------------------------------------------
        cursor.execute("SELECT MAX(CAST(ticket_no AS INTEGER)) FROM tickets")
        highest_ticket = cursor.fetchone()[0] or 0
        ticket_no = str(highest_ticket + 1).zfill(16)

        # -------------------------------------------------
        # 7. Create booking
        # -------------------------------------------------
        cursor.execute(
            """
            INSERT INTO bookings (
                book_ref,
                book_date,
                total_amount
            )
            VALUES (?, ?, ?)
            """,
            (
                book_ref,
                datetime.now(pytz.UTC).isoformat(),
                amount
            )
        )

        # -------------------------------------------------
        # 8. Create ticket
        # -------------------------------------------------
        cursor.execute(
            """
            INSERT INTO tickets (
                ticket_no,
                book_ref,
                passenger_id
            )
            VALUES (?, ?, ?)
            """,
            (
                ticket_no,
                book_ref,
                passenger_id
            )
        )

        # -------------------------------------------------
        # 9. Connect ticket to flight
        # -------------------------------------------------
        cursor.execute(
            """
            INSERT INTO ticket_flights (
                ticket_no,
                flight_id,
                fare_conditions,
                amount
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                ticket_no,
                flight_id,
                fare_conditions,
                amount
            )
        )

        conn.commit()

        return (
            "BOOKING CONFIRMED\n"
            f"Booking Reference: {book_ref}\n"
            f"Ticket Number: {ticket_no}\n"
            f"Passenger: {passenger_id}\n"
            f"Flight: {flight[1]}\n"
            f"Route: {flight[2]} -> {flight[3]}\n"
            f"Departure: {flight[4]}\n"
            f"Fare: {fare_conditions}\n"
            f"Amount: {amount}"
        )

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()