"""Shared fixtures.

The environment is configured BEFORE any application module is imported: the
app reads its settings at import time. Tests use
  * a small fixture SQLite database (rebuilt for every test),
  * a temporary embedded Qdrant store with the real knowledge base indexed,
  * a scripted chat model instead of Gemini (no API key or network needed).
"""

import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

_TMP = Path(tempfile.mkdtemp(prefix="csc-tests-"))
os.environ.update(
    {
        "GEMINI_API_KEY": "",
        "SQLITE_DB_PATH": str(_TMP / "travel.sqlite"),
        "QDRANT_PATH": str(_TMP / "qdrant"),
        "QDRANT_URL": "",
        "KNOWLEDGE_BASE_DIR": str(ROOT / "knowledge_base"),
        "LOG_LEVEL": "WARNING",
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
        "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
        "DEMO_PASSENGER_ID": "",
    }
)

import pytest  # noqa: E402

from tests.fake_llm import ScriptedChatModel  # noqa: E402

PASSENGER = "1111 222333"
OTHER_PASSENGER = "4444 555666"
BOOK_REF = "ABC123"
TICKET = "7240000000000001"
OTHER_TICKET = "7240000000000002"


def _ts(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat(sep=" ")


def build_fixture_db(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE bookings (book_ref TEXT, book_date TEXT, total_amount REAL);
        CREATE TABLE tickets (ticket_no TEXT, book_ref TEXT, passenger_id TEXT);
        CREATE TABLE flights (flight_id INTEGER, flight_no TEXT, scheduled_departure TEXT,
            scheduled_arrival TEXT, departure_airport TEXT, arrival_airport TEXT, status TEXT,
            aircraft_code TEXT, actual_departure TEXT, actual_arrival TEXT);
        CREATE TABLE ticket_flights (ticket_no TEXT, flight_id INTEGER, fare_conditions TEXT, amount REAL);
        CREATE TABLE boarding_passes (ticket_no TEXT, flight_id INTEGER, boarding_no INTEGER, seat_no TEXT);
        CREATE TABLE hotels (id INTEGER, name TEXT, location TEXT, price_tier TEXT,
            checkin_date TEXT, checkout_date TEXT, booked INTEGER);
        CREATE TABLE car_rentals (id INTEGER, name TEXT, location TEXT, price_tier TEXT,
            start_date TEXT, end_date TEXT, booked INTEGER);
        CREATE TABLE trip_recommendations (id INTEGER, name TEXT, location TEXT, keywords TEXT,
            details TEXT, booked INTEGER);
        """
    )
    flights = [
        (1, "LX0112", _ts(timedelta(days=5)), _ts(timedelta(days=5, hours=1)), "BSL", "CDG", "Scheduled", "SU9", None, None),
        (2, "LX0114", _ts(timedelta(days=6)), _ts(timedelta(days=6, hours=1)), "BSL", "CDG", "Scheduled", "SU9", None, None),
        (3, "LX0116", _ts(timedelta(hours=1)), _ts(timedelta(hours=2)), "BSL", "CDG", "Scheduled", "SU9", None, None),
        (4, "LX0200", _ts(timedelta(days=9)), _ts(timedelta(days=9, hours=2)), "ZRH", "LHR", "Scheduled", "320", None, None),
    ]
    conn.executemany("INSERT INTO flights VALUES (?,?,?,?,?,?,?,?,?,?)", flights)
    conn.executemany(
        "INSERT INTO bookings VALUES (?,?,?)",
        [(BOOK_REF, _ts(timedelta(days=-10)), 420.0), ("ZZZ999", _ts(timedelta(days=-3)), 300.0)],
    )
    conn.executemany(
        "INSERT INTO tickets VALUES (?,?,?)",
        [(TICKET, BOOK_REF, PASSENGER), (OTHER_TICKET, "ZZZ999", OTHER_PASSENGER)],
    )
    conn.executemany(
        "INSERT INTO ticket_flights VALUES (?,?,?,?)",
        [(TICKET, 1, "Economy", 420.0), (OTHER_TICKET, 4, "Business", 300.0)],
    )
    conn.execute("INSERT INTO boarding_passes VALUES (?,?,?,?)", (TICKET, 1, 1, "12A"))
    conn.executemany(
        "INSERT INTO hotels VALUES (?,?,?,?,?,?,?)",
        [
            (1, "Hilton Basel", "Basel", "Luxury", "2026-10-11", "2026-10-13", 0),
            (2, "Ibis Paris", "Paris", "Midscale", "2026-10-11", "2026-10-13", 0),
        ],
    )
    conn.executemany(
        "INSERT INTO car_rentals VALUES (?,?,?,?,?,?,?)",
        [
            (1, "Europcar", "Basel", "Economy", "2026-10-11", "2026-10-13", 0),
            (2, "Avis", "Paris", "Luxury", "2026-10-11", "2026-10-13", 0),
        ],
    )
    conn.executemany(
        "INSERT INTO trip_recommendations VALUES (?,?,?,?,?,?)",
        [
            (1, "Basel Minster", "Basel", "landmark, history", "Visit the Gothic cathedral.", 0),
            (2, "Louvre Museum", "Paris", "art, museum", "See the Mona Lisa.", 0),
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture(scope="session")
def vector_store():
    """Index the real knowledge base and the fixture tables once per test session."""
    build_fixture_db(os.environ["SQLITE_DB_PATH"])
    from vectorizer.app.vectordb.vectordb import VectorDB

    for table, collection in [
        ("knowledge_base", "knowledge_base_collection"),
        ("hotels", "hotels_collection"),
        ("car_rentals", "car_rentals_collection"),
        ("trip_recommendations", "excursions_collection"),
        ("flights", "flights_collection"),
    ]:
        VectorDB(table_name=table, collection_name=collection, create_collection=True).create_embeddings()
    yield
    from vectorizer.app.vectordb.client import close_qdrant_client

    close_qdrant_client()


@pytest.fixture
def db():
    """A fresh fixture database for each test (tools mutate it)."""
    path = os.environ["SQLITE_DB_PATH"]
    build_fixture_db(path)
    yield path


@pytest.fixture
def scripted_llm():
    return ScriptedChatModel()


@pytest.fixture
def make_graph(scripted_llm):
    from langgraph.checkpoint.memory import MemorySaver

    from customer_support_chat.app.graph import build_graph

    def _make():
        return build_graph(llm=scripted_llm, checkpointer=MemorySaver())

    return _make


@pytest.fixture
def service(make_graph, db, vector_store):
    from customer_support_chat.app.services.chat_service import ChatService

    return ChatService(graph_factory=make_graph, db_path=db)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
