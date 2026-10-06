"""Duffel API v2 responses recorded in test mode (LHR-JFK, 2026-11-20), in fixtures/duffel/.

Trimmed only of large fields the adapter never reads (available services, loyalty
programmes, ...). The order's passenger is the test traveller used for the recording.
"""

import json
from pathlib import Path

DIR = Path(__file__).parent / "fixtures" / "duffel"


def _load(name: str) -> dict:
    return json.loads((DIR / name).read_text(encoding="utf-8"))


OFFER_REQUEST = _load("offer_request.json")  # a 1-stop SWISS offer, then the direct ZZ one
OFFER = _load("offer.json")                  # Duffel Airways ZZ3829, USD 224.41
ORDER = _load("order.json")                  # booking reference JPZ3RG
ORDER_CANCELLATION = _load("order_cancellation.json")
ORDER_CANCELLATION_CONFIRMED = _load("order_cancellation_confirmed.json")
NOT_FOUND = _load("error_not_found.json")

CONNECTING, DIRECT = OFFER_REQUEST["data"]["offers"]
PASSENGER_ID = DIRECT["passengers"][0]["id"]
