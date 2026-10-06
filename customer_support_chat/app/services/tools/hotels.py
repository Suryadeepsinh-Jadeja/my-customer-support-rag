from vectorizer.app.vectordb.vectordb import VectorDB
from customer_support_chat.app.core.settings import get_settings
from langchain_core.tools import tool
import sqlite3
from contextlib import closing
from typing import Optional, Union, List, Dict
from datetime import datetime, date

settings = get_settings()
db = settings.SQLITE_DB_PATH
hotels_vectordb = VectorDB(table_name="hotels", collection_name="hotels_collection")

@tool
def search_hotels(
    query: str,
    limit: int = 5,
) -> List[Dict]:
    """Search partner hotels with a natural language query, e.g. "luxury hotel in Zurich"."""
    search_results = hotels_vectordb.search(query, limit=limit)

    hotels = []
    for result in search_results:
        payload = result.payload
        hotels.append({
            "id": payload["id"],
            "name": payload["name"],
            "location": payload["location"],
            "price_tier": payload["price_tier"],
            "checkin_date": payload["checkin_date"],
            "checkout_date": payload["checkout_date"],
            "booked": payload["booked"],
            "chunk": payload["content"],
            "similarity": result.score,
        })
    return hotels

def _write(*statements) -> int:
    """Run UPDATE statements in one transaction; return the rows changed by the last one."""
    with closing(sqlite3.connect(db)) as conn:
        cursor = conn.cursor()
        for sql, params in statements:
            cursor.execute(sql, params)
        conn.commit()
        return cursor.rowcount


@tool
def book_hotel(hotel_id: int) -> str:
    """Book a hotel by its ID."""
    if _write(("UPDATE hotels SET booked = 1 WHERE id = ?", (hotel_id,))):
        return f"Hotel {hotel_id} successfully booked."
    return f"No hotel found with ID {hotel_id}."

@tool
def update_hotel(
    hotel_id: int,
    checkin_date: Optional[date] = None,
    checkout_date: Optional[date] = None,
) -> str:
    """Update a hotel booking's check-in and/or check-out dates (YYYY-MM-DD) by its ID."""
    if not checkin_date and not checkout_date:
        return "Nothing to update: provide a new checkin_date and/or checkout_date (YYYY-MM-DD)."

    statements = []
    if checkin_date:
        statements.append(("UPDATE hotels SET checkin_date = ? WHERE id = ?", (checkin_date.strftime('%Y-%m-%d'), hotel_id)))
    if checkout_date:
        statements.append(("UPDATE hotels SET checkout_date = ? WHERE id = ?", (checkout_date.strftime('%Y-%m-%d'), hotel_id)))
    if _write(*statements):
        return f"Hotel {hotel_id} successfully updated."
    return f"No hotel found with ID {hotel_id}."

@tool
def cancel_hotel(hotel_id: int) -> str:
    """Cancel a hotel by its ID."""
    if _write(("UPDATE hotels SET booked = 0 WHERE id = ?", (hotel_id,))):
        return f"Hotel {hotel_id} successfully cancelled."
    return f"No hotel found with ID {hotel_id}."
