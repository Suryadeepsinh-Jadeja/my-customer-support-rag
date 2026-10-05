from vectorizer.app.vectordb.vectordb import VectorDB
from customer_support_chat.app.core.settings import get_settings
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
import sqlite3
from typing import Optional, Union, List, Dict
from datetime import datetime, date
import pytz

settings = get_settings()
db = settings.SQLITE_DB_PATH
flights_vectordb = VectorDB(table_name="flights", collection_name="flights_collection")


@tool
def fetch_user_flight_information(*, config: RunnableConfig) -> List[Dict]:
    """Fetch all tickets for the user along with corresponding flight information and seat assignments."""
    configuration = config.get("configurable", {})
    passenger_id = configuration.get("passenger_id", None)
    if not passenger_id:
        raise ValueError("No passenger ID configured.")

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
    query: str,
    limit: int = 2,
) -> List[Dict]:
    """Search for flights based on a natural language query."""
    search_results = flights_vectordb.search(query, limit=limit)

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
    """Update the user's ticket to a new valid flight."""
    configuration = config.get("configurable", {})
    passenger_id = configuration.get("passenger_id", None)
    if not passenger_id:
        raise ValueError("No passenger ID configured.")

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
        return f"Ticket {ticket_no} not found for passenger {passenger_id}."

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
    configuration = config.get("configurable", {})
    passenger_id = configuration.get("passenger_id", None)
    if not passenger_id:
        raise ValueError("No passenger ID configured.")

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
        return f"Ticket {ticket_no} not found for passenger {passenger_id}."

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

    configuration = config.get("configurable", {})
    passenger_id = configuration.get("passenger_id")

    if not passenger_id:
        raise ValueError("No passenger ID configured.")

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