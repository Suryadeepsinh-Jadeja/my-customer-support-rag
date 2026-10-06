from vectorizer.app.vectordb.vectordb import VectorDB
from customer_support_chat.app.core.settings import get_settings
from langchain_core.tools import tool
import sqlite3
from contextlib import closing
from typing import List, Dict, Optional, Union
from datetime import datetime, date

settings = get_settings()
db = settings.SQLITE_DB_PATH

cars_vectordb = VectorDB(table_name="car_rentals", collection_name="car_rentals_collection")

@tool
def search_car_rentals(
    query: str,
    limit: int = 5,
) -> List[Dict]:
    """Search car rentals with a natural language query, e.g. "economy car in Basel"."""
    search_results = cars_vectordb.search(query, limit=limit)

    rentals = []
    for result in search_results:
        payload = result.payload
        rentals.append({
            "id": payload["id"],
            "name": payload["name"],
            "location": payload["location"],
            "price_tier": payload["price_tier"],
            "start_date": payload["start_date"],
            "end_date": payload["end_date"],
            "booked": payload["booked"],
            "chunk": payload["content"],
            "similarity": result.score,
        })
    return rentals

def _write(*statements) -> int:
    """Run UPDATE statements in one transaction; return the rows changed by the last one."""
    with closing(sqlite3.connect(db)) as conn:
        cursor = conn.cursor()
        for sql, params in statements:
            cursor.execute(sql, params)
        conn.commit()
        return cursor.rowcount


@tool
def book_car_rental(rental_id: int) -> str:
    """Book a car rental by its ID."""
    if _write(("UPDATE car_rentals SET booked = 1 WHERE id = ?", (rental_id,))):
        return f"Car rental {rental_id} successfully booked."
    return f"No car rental found with ID {rental_id}."

@tool
def update_car_rental(
    rental_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> str:
    """Update a car rental's start and/or end dates (YYYY-MM-DD) by its ID."""
    if not start_date and not end_date:
        return "Nothing to update: provide a new start_date and/or end_date (YYYY-MM-DD)."

    statements = []
    if start_date:
        statements.append(("UPDATE car_rentals SET start_date = ? WHERE id = ?", (start_date.strftime('%Y-%m-%d'), rental_id)))
    if end_date:
        statements.append(("UPDATE car_rentals SET end_date = ? WHERE id = ?", (end_date.strftime('%Y-%m-%d'), rental_id)))
    if _write(*statements):
        return f"Car rental {rental_id} successfully updated."
    return f"No car rental found with ID {rental_id}."

@tool
def cancel_car_rental(rental_id: int) -> str:
    """Cancel a car rental by its ID."""
    if _write(("UPDATE car_rentals SET booked = 0 WHERE id = ?", (rental_id,))):
        return f"Car rental {rental_id} successfully cancelled."
    return f"No car rental found with ID {rental_id}."
