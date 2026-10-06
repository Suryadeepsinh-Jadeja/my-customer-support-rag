from vectorizer.app.vectordb.vectordb import VectorDB
from customer_support_chat.app.core.settings import get_settings
from langchain_core.tools import tool
import sqlite3
from contextlib import closing
from typing import Optional, List, Dict

settings = get_settings()
db = settings.SQLITE_DB_PATH
excursions_vectordb = VectorDB(table_name="trip_recommendations", collection_name="excursions_collection")

@tool
def search_trip_recommendations(
    query: str,
    limit: int = 5,
) -> List[Dict]:
    """Search excursions/trip recommendations with a natural language query, e.g. "art museum in Basel"."""
    search_results = excursions_vectordb.search(query, limit=limit)

    recommendations = []
    for result in search_results:
        payload = result.payload
        recommendations.append({
            "id": payload["id"],
            "name": payload["name"],
            "location": payload["location"],
            "keywords": payload["keywords"],
            "details": payload["details"],
            "booked": payload["booked"],
            "chunk": payload["content"],
            "similarity": result.score,
        })
    return recommendations

def _write(*statements) -> int:
    """Run UPDATE statements in one transaction; return the rows changed by the last one."""
    with closing(sqlite3.connect(db)) as conn:
        cursor = conn.cursor()
        for sql, params in statements:
            cursor.execute(sql, params)
        conn.commit()
        return cursor.rowcount


@tool
def book_excursion(recommendation_id: int) -> str:
    """Book an excursion by its ID."""
    if _write(("UPDATE trip_recommendations SET booked = 1 WHERE id = ?", (recommendation_id,))):
        return f"Excursion {recommendation_id} successfully booked."
    return f"No excursion found with ID {recommendation_id}."

@tool
def update_excursion(recommendation_id: int, details: str) -> str:
    """Update an excursion's details by its ID."""
    if _write(("UPDATE trip_recommendations SET details = ? WHERE id = ?", (details, recommendation_id))):
        return f"Excursion {recommendation_id} successfully updated."
    return f"No excursion found with ID {recommendation_id}."

@tool
def cancel_excursion(recommendation_id: int) -> str:
    """Cancel an excursion by its ID."""
    if _write(("UPDATE trip_recommendations SET booked = 0 WHERE id = ?", (recommendation_id,))):
        return f"Excursion {recommendation_id} successfully cancelled."
    return f"No excursion found with ID {recommendation_id}."
