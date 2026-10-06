from vectorizer.app.vectordb.vectordb import VectorDB
from customer_support_chat.app.core.settings import get_settings
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
import sqlite3
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

    conn = sqlite3.connect(db)
    cursor = conn.cursor()

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
    cursor.execute(query, (passenger_id,))
    rows = cursor.fetchall()
    column_names = [column[0] for column in cursor.description]
    results = [dict(zip(column_names, row)) for row in rows]

    cursor.close()
    conn.close()

    return results

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
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
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
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        conn.close()
        return rows

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

@tool
def update_ticket_to_new_flight(
    ticket_no: str, new_flight_id: int, *, config: RunnableConfig
) -> str:
    """Update the user's ticket to a new valid flight (use the flight_id returned by search_flights)."""
    passenger_id = get_passenger_id(config)

    conn = sqlite3.connect(db)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT departure_airport, arrival_airport, scheduled_departure FROM flights WHERE flight_id = ?",
        (new_flight_id,),
    )
    new_flight = cursor.fetchone()
    if not new_flight:
        conn.close()
        return f"Invalid new flight ID {new_flight_id} provided."

    departure = datetime.fromisoformat(str(new_flight[2]))
    if departure.tzinfo is None:
        departure = departure.replace(tzinfo=pytz.UTC)
    if departure - datetime.now(pytz.UTC) < timedelta(hours=MIN_HOURS_BEFORE_DEPARTURE):
        conn.close()
        return (
            f"Not permitted to reschedule to flight {new_flight_id}: it departs in less than "
            f"{MIN_HOURS_BEFORE_DEPARTURE} hours (scheduled {new_flight[2]})."
        )

    # Check if the ticket exists and belongs to the passenger
    cursor.execute(
        "SELECT * FROM tickets WHERE ticket_no = ? AND passenger_id = ?",
        (ticket_no, passenger_id),
    )
    ticket = cursor.fetchone()
    if not ticket:
        conn.close()
        return f"Ticket {ticket_no} was not found in the signed-in customer's bookings."

    # Update the flight in ticket_flights
    cursor.execute(
        "UPDATE ticket_flights SET flight_id = ? WHERE ticket_no = ?",
        (new_flight_id, ticket_no),
    )
    conn.commit()

    if cursor.rowcount > 0:
        conn.close()
        return f"Ticket {ticket_no} successfully updated to flight {new_flight_id}."
    else:
        conn.close()
        return f"Failed to update ticket {ticket_no}."

@tool
def cancel_ticket(ticket_no: str, *, config: RunnableConfig) -> str:
    """Cancel the user's ticket and remove it from the database."""
    passenger_id = get_passenger_id(config)

    conn = sqlite3.connect(db)
    cursor = conn.cursor()

    # Check if the ticket exists and belongs to the passenger
    cursor.execute(
        "SELECT * FROM tickets WHERE ticket_no = ? AND passenger_id = ?",
        (ticket_no, passenger_id),
    )
    ticket = cursor.fetchone()
    if not ticket:
        conn.close()
        return f"Ticket {ticket_no} was not found in the signed-in customer's bookings."

    # Delete from ticket_flights
    cursor.execute(
        "DELETE FROM ticket_flights WHERE ticket_no = ?",
        (ticket_no,),
    )
    # Delete from tickets
    cursor.execute(
        "DELETE FROM tickets WHERE ticket_no = ?",
        (ticket_no,),
    )
    conn.commit()

    conn.close()
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
        # 5. Generate booking reference
        # -------------------------------------------------
        cursor.execute(
            """
            SELECT book_ref
            FROM bookings
            ORDER BY rowid DESC
            LIMIT 1
            """
        )

        last_booking = cursor.fetchone()

        if last_booking:
            try:
                next_number = int(last_booking[0], 16) + 1
            except ValueError:
                next_number = 1
        else:
            next_number = 1

        book_ref = f"{next_number:06X}"

        # -------------------------------------------------
        # 6. Generate ticket number
        # -------------------------------------------------
        cursor.execute(
            """
            SELECT ticket_no
            FROM tickets
            ORDER BY rowid DESC
            LIMIT 1
            """
        )

        last_ticket = cursor.fetchone()

        if last_ticket:
            try:
                next_ticket = int(last_ticket[0]) + 1
            except ValueError:
                next_ticket = 1
        else:
            next_ticket = 1

        ticket_no = str(next_ticket).zfill(16)

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