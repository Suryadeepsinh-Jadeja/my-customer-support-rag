"""A deterministic, rule-based stand-in for Gemini (LLM_PROVIDER=fake).

For end-to-end tests and keyless demos only; refused in production. It understands the
demo conversation (flight number, arrival, baggage, booking a flight, cancelling) and
drives the real tools, so everything around the model (routing, tools, sources, cards,
confirmations) is exercised for real. Embeddings are hashed bags of words, so retrieval
works without a key too.
"""

import hashlib
import math
import re
from datetime import date
from typing import Any

from app.services.llm_service import (
    ChatTurn,
    Content,
    HistoryItem,
    LLMError,
    LLMService,
    ModelTurn,
    ToolCall,
    ToolResult,
    ToolSpec,
)

CITIES = {"london": "LHR", "paris": "CDG", "zurich": "ZRH", "new york": "JFK",
          "mumbai": "BOM", "dubai": "DXB", "rome": "FCO"}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]


def _vector(text: str) -> list[float]:
    v = [0.0] * 768
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        v[int(hashlib.md5(token.encode()).hexdigest(), 16) % 768] += 1.0  # noqa: S324
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def travel_date(text: str) -> date | None:
    """'October 20' or '20 October' -> the next such date."""
    m = re.search(rf"({'|'.join(MONTHS)})\s+(\d{{1,2}})|(\d{{1,2}})\s+({'|'.join(MONTHS)})",
                  text.lower())
    if not m:
        return None
    month = MONTHS.index(m.group(1) or m.group(4)) + 1
    day = int(m.group(2) or m.group(3))
    today = date.today()
    try:
        candidate = date(today.year, month, day)
        return candidate if candidate >= today else date(today.year + 1, month, day)
    except ValueError:
        return None


def _intent(message: str):
    from app.agents.supervisor import Intent

    m = message.lower()
    booking = any(w in m for w in ("book", "cancel", "offer_id", "change"))
    if any(w in m for w in ("hotel", "room", "check-in", "check in")):
        domain = "hotel"
    elif any(w in m for w in ("flight", "fly", "arrive", "baggage", "cancel", "offer_id")):
        domain = "flight"
    elif any(w in m for w in ("passport", "visa", "document")):
        domain = "document"
    else:
        domain = "general"
    return Intent(domain=domain, needs_booking=booking,  # type: ignore[arg-type]
                  needs_documents=domain in ("flight", "document"))


def _fields(result: dict[str, Any]) -> tuple[dict[str, str], str | None]:
    docs = result.get("documents") or []
    if not docs:
        return {}, None
    return {f["field"]: f["value"] for f in docs[0]["fields"]}, docs[0]["document"]


class FakeLLM(LLMService):
    def __init__(self) -> None:
        super().__init__(api_key="fake", model="fake", timeout=5)

    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        return [_vector(t) for t in texts]

    async def generate(self, *, purpose: str, system: str, contents: list[Content],
                       temperature: float = 0.2) -> str:
        return "The user and the assistant discussed the user's trip."

    async def generate_structured(self, *, purpose: str, system: str,
                                  contents: list[Content], schema, temperature: float = 0.0):
        from app.agents.supervisor import Intent

        if schema is not Intent:  # document analysis falls back to the built-in rules
            raise LLMError("the fake LLM doesn't analyse documents")
        text = next((c for c in contents if isinstance(c, str)), "")
        latest = re.search(r"<latest_user_message>\s*(.*?)\s*</latest_user_message>", text, re.S)
        return _intent(latest.group(1) if latest else text)

    async def generate_with_tools(self, *, purpose: str, system: str,
                                  history: list[HistoryItem], tools: list[ToolSpec],
                                  temperature: float = 0.2) -> ModelTurn:
        user = ""
        done: dict[str, dict[str, Any]] = {}
        for item in history:
            if isinstance(item, ChatTurn) and item.role == "user":
                user, done = item.text, {}
            elif isinstance(item, ToolResult):
                done[item.name] = item.response.get("untrusted_data", {})
        return self._step(user.lower(), done, {t.name for t in tools})

    @staticmethod
    def _tool(name: str, **args: Any) -> ModelTurn:
        return ModelTurn(calls=[ToolCall(name, args)])

    def _step(self, m: str, done: dict[str, dict[str, Any]], tools: set[str]) -> ModelTurn:
        if "offer_id:" in m:
            offer_id = m.split("offer_id:", 1)[1].strip().rstrip(")").strip()
            tool = f"book_{offer_id.split('|', 1)[0]}" if "|" in offer_id else "book_flight"
            if tool not in done:
                return self._tool(tool, offer_id=offer_id)
            result = done[tool]
            if "error" in result:
                return ModelTurn(text=f"I couldn't prepare that booking: {result['error']}")
            s = result["summary"]
            return ModelTurn(text=f"I've prepared your booking: {s['title']} on "
                                  f"{s['start_date']} for {s['price']:.2f} {s['currency']}. "
                                  "Please press Confirm on the card to book it.")

        if "cancel" in m:
            if "get_bookings" not in done:
                return self._tool("get_bookings")
            if "cancel_booking" not in done:
                active = [b for b in done["get_bookings"].get("bookings", [])
                          if b["status"] in ("confirmed", "modified")]
                if not active:
                    return ModelTurn(text="You have no active bookings to cancel.")
                return self._tool("cancel_booking", booking_id=active[0]["booking_id"])
            result = done["cancel_booking"]
            if "error" in result:
                return ModelTurn(text=f"I couldn't prepare the cancellation: {result['error']}")
            refund = result["summary"]["refund"]
            return ModelTurn(text=f"Cancelling {result['summary']['booking']['title']} refunds "
                                  f"{refund['refund_amount']:.2f} {refund['currency']} under "
                                  "the provider's terms. Press Confirm on the card to cancel.")

        if "book" in m and ("flight" in m or "fly" in m):
            day = travel_date(m)
            destination = next((code for city, code in CITIES.items() if city in m), None)
            if not day or not destination:
                return ModelTurn(text="Where and on which date would you like to fly?")
            if "get_user_profile" not in done:
                return self._tool("get_user_profile")
            if "search_flights" not in done:
                origin = done["get_user_profile"].get("home_airport") or "BOM"
                return self._tool("search_flights", origin=origin, destination=destination,
                                  date=day.isoformat())
            offers = done["search_flights"].get("offers", [])
            if not offers:
                return ModelTurn(text="I couldn't find flights for that date.")
            cheapest = min(offers, key=lambda o: o["price"])
            return ModelTurn(text=f"I found {len(offers)} flights (test inventory). The "
                                  f"cheapest is {cheapest['title']} at {cheapest['price']:.2f} "
                                  f"{cheapest['currency']}. Select the one you'd like.")

        lookups = [("flight number", "flight_number"), ("arrive", "arrival_time"),
                   ("baggage", "baggage_allowance")]
        for words, field in lookups:
            if words not in m:
                continue
            if "get_document_fields" not in done:
                return self._tool("get_document_fields", field=field)
            values, document = _fields(done["get_document_fields"])
            if field == "baggage_allowance" and "search_policies" not in done:
                return self._tool("search_policies", query="checked baggage allowance")
            if field not in values:
                return ModelTurn(text="I couldn't verify that from your documents.")
            if field == "arrival_time":
                where = values.get("arrival_airport")
                return ModelTurn(text=f"According to your {document}, you arrive at "
                                      f"{values[field]}{f' in {where}' if where else ''}.")
            label = field.replace("_", " ")
            return ModelTurn(text=f"According to your {document}, your {label} is "
                                  f"{values[field]}.")

        return ModelTurn(text="I'm the test assistant. Ask about your flight number, arrival "
                              "time or baggage, book a flight, or cancel a booking.")

