"""Deterministic mock inventory for flights, hotels, cars and excursions.

Everything is generated from the search parameters with a seeded RNG, so the same search
always returns the same offers and an offer id can be resolved again without storage.
What is offered (airline, flight number, hotel, car) depends only on the route or city;
prices also depend on the date. All results are marked as test data (`provider="mock"`,
`test_booking=True`).
"""

import random
import secrets
from datetime import date, datetime, timedelta
from typing import Any

from app.providers.base import BookingProvider, ProviderError

CURRENCY = "USD"
OFFERS_PER_SEARCH = 5

# Parameter order inside offer ids, per kind.
PARAMS = {
    "flight": ["origin", "destination", "date", "cabin"],
    "hotel": ["city", "check_in", "check_out", "guests"],
    "car": ["location", "pickup_date", "dropoff_date"],
    "excursion": ["city", "date", "participants"],
}
DATE_PARAMS = {"date", "check_in", "check_out", "pickup_date", "dropoff_date"}

AIRLINES = [("LX", "SWISS"), ("LH", "Lufthansa"), ("BA", "British Airways"),
            ("AF", "Air France"), ("KL", "KLM"), ("EK", "Emirates"), ("TK", "Turkish Airlines")]
CABIN_FACTOR = {"economy": 1.0, "premium_economy": 1.6, "business": 3.2, "first": 5.0}
# fare name, price factor, checked baggage, refund rule
FARES = [("Light", 1.0, "Hand baggage only", "none"),
         ("Classic", 1.3, "1 x 23 kg", "fee"),
         ("Flex", 1.8, "2 x 23 kg", "full")]
CANCELLATION_FEE = 150.0  # Classic fares; the refund policy still quotes this in CHF

HOTELS = ["Grand Central Hotel", "Riverside Suites", "Old Town Inn", "Park Plaza",
          "Harbour View Hotel", "City Lodge", "The Royal Garden"]
ROOMS = ["Standard double", "Superior double", "Deluxe king", "Junior suite"]
CAR_COMPANIES = ["Hertz", "Avis", "Europcar", "Sixt", "Enterprise"]
CAR_CLASSES = [("Economy", "VW Polo or similar", 45), ("Compact", "VW Golf or similar", 58),
               ("Intermediate", "Toyota Corolla or similar", 72),
               ("SUV", "VW Tiguan or similar", 95), ("Premium", "BMW 5 Series or similar", 140)]
EXCURSIONS = [("City walking tour", 3, 35), ("Museum pass and guided visit", 4, 55),
              ("Day trip to the countryside", 9, 120), ("Food tasting tour", 3, 75),
              ("Boat cruise", 2, 45), ("Mountain or coastal hike", 6, 90)]


def _rng(*parts: object) -> random.Random:
    return random.Random("|".join(str(p) for p in parts))  # noqa: S311 (mock data, not security)


def _day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ProviderError("invalid_date", "That date isn't valid.") from exc


def _offer_id(kind: str, params: dict[str, Any], index: int) -> str:
    return "|".join([kind, *(str(params[p]) for p in PARAMS[kind]), str(index)])


def _common(kind: str, params: dict[str, Any], index: int, title: str, price: float,
            start: str, end: str | None = None) -> dict[str, Any]:
    return {"offer_id": _offer_id(kind, params, index), "kind": kind, "provider": "mock",
            "test_booking": True, "title": title, "price": round(price, 2),
            "currency": CURRENCY, "start_date": start, "end_date": end or start}


def _flight(p: dict[str, Any], i: int) -> dict[str, Any]:
    route = _rng("flight", p["origin"], p["destination"], i)
    code, airline = route.choice(AIRLINES)
    number = f"{code}{route.randint(100, 1999)}"
    duration = route.randint(70, 780)
    stops = 0 if duration < 300 or route.random() < 0.5 else 1
    dep = datetime.combine(_day(p["date"]), datetime.min.time()) + timedelta(
        hours=route.randint(6, 22), minutes=route.choice([0, 15, 30, 45]))
    arr = dep + timedelta(minutes=duration + 75 * stops)
    fare, factor, baggage, refund = FARES[i % len(FARES)]
    jitter = _rng("price", p["origin"], p["destination"], p["date"], i).uniform(0.85, 1.25)
    price = (60 + duration * 0.55) * factor * CABIN_FACTOR[p["cabin"]] * jitter
    offer = _common("flight", p, i, f"{airline} {number} {p['origin']}-{p['destination']}",
                    price, dep.date().isoformat(), arr.date().isoformat())
    return offer | {
        "airline": airline, "flight_number": number, "origin": p["origin"],
        "destination": p["destination"], "departure": dep.isoformat(timespec="minutes"),
        "arrival": arr.isoformat(timespec="minutes"),
        "duration_minutes": duration + 75 * stops, "stops": stops, "cabin": p["cabin"],
        "fare": fare, "baggage": baggage, "refund_rule": refund,
    }


def _hotel(p: dict[str, Any], i: int) -> dict[str, Any]:
    check_in, check_out = _day(p["check_in"]), _day(p["check_out"])
    nights = (check_out - check_in).days
    if nights < 1:
        raise ProviderError("invalid_dates", "Check-out must be after check-in.")
    place = _rng("hotel", p["city"].lower(), i)
    name = f"{place.choice(HOTELS)} {p['city'].title()}"
    nightly = place.randint(90, 320) * _rng("price", p["city"], p["check_in"], i).uniform(0.9, 1.2)
    refundable = place.random() < 0.6
    offer = _common("hotel", p, i, name, nightly * nights * max(1, int(p["guests"])) ** 0.5,
                    check_in.isoformat(), check_out.isoformat())
    return offer | {
        "hotel_name": name, "city": p["city"].title(),
        "address": f"{place.randint(1, 250)} {place.choice(['Main', 'Park', 'River', 'Station'])} "
                   f"Street, {p['city'].title()}",
        "stars": place.randint(3, 5), "room_type": place.choice(ROOMS), "nights": nights,
        "guests": int(p["guests"]), "refundable": refundable,
        "refund_rule": "full" if refundable else "none",
    }


def _car(p: dict[str, Any], i: int) -> dict[str, Any]:
    pickup, dropoff = _day(p["pickup_date"]), _day(p["dropoff_date"])
    days = (dropoff - pickup).days
    if days < 1:
        raise ProviderError("invalid_dates", "Drop-off must be after pick-up.")
    place = _rng("car", p["location"].lower(), i)
    company = place.choice(CAR_COMPANIES)
    car_class, model, daily = CAR_CLASSES[i % len(CAR_CLASSES)]
    price = daily * days * _rng("price", p["location"], p["pickup_date"], i).uniform(0.9, 1.2)
    offer = _common("car", p, i, f"{company} {car_class} in {p['location']}", price,
                    pickup.isoformat(), dropoff.isoformat())
    return offer | {"company": company, "car_class": car_class, "model": model,
                    "pickup_location": p["location"], "days": days, "refund_rule": "full"}


def _excursion(p: dict[str, Any], i: int) -> dict[str, Any]:
    day = _day(p["date"])
    title, hours, per_person = EXCURSIONS[_rng("excursion", p["city"].lower(), i).randrange(
        len(EXCURSIONS))]
    title = f"{title}, {p['city'].title()}"
    price = per_person * int(p["participants"]) * _rng("price", p["city"], p["date"], i).uniform(
        0.9, 1.15)
    offer = _common("excursion", p, i, title, price, day.isoformat())
    return offer | {"city": p["city"].title(), "duration_hours": hours,
                    "participants": int(p["participants"]), "refund_rule": "full"}


GENERATORS = {"flight": _flight, "hotel": _hotel, "car": _car, "excursion": _excursion}


class MockProvider(BookingProvider):
    name = "mock"

    def __init__(self, kind: str):
        self.kind = kind

    async def search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        params = {k: params[k] for k in PARAMS[self.kind]}
        return [GENERATORS[self.kind](params, i) for i in range(OFFERS_PER_SEARCH)]

    async def get_offer(self, offer_id: str) -> dict[str, Any]:
        parts = offer_id.split("|")
        names = PARAMS[self.kind]
        if (len(parts) != len(names) + 2 or parts[0] != self.kind
                or not parts[-1].isdigit() or int(parts[-1]) >= OFFERS_PER_SEARCH):
            raise ProviderError("offer_not_found", "That offer no longer exists. Search again.")
        params = dict(zip(names, parts[1:-1], strict=True))
        if self.kind == "flight" and params["cabin"] not in CABIN_FACTOR:
            raise ProviderError("offer_not_found", "That offer no longer exists. Search again.")
        if any(not p.isdigit() for k, p in params.items() if k in {"guests", "participants"}):
            raise ProviderError("offer_not_found", "That offer no longer exists. Search again.")
        return GENERATORS[self.kind](params, int(parts[-1]))

    async def book(self, offer: dict[str, Any], travellers: list[dict[str, Any]],
                   contact: dict[str, Any]) -> dict[str, Any]:
        if _day(offer["start_date"]) < date.today():
            raise ProviderError("offer_expired", "That date is in the past.")
        return {"reference": "MK" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
                                            for _ in range(6))}

    async def refund_quote(self, details: dict[str, Any], amount: float) -> dict[str, Any]:
        rule = details.get("refund_rule", "none")
        refund = amount if rule == "full" else max(0.0, amount - CANCELLATION_FEE) \
            if rule == "fee" else 0.0
        return {"refund_amount": round(refund, 2), "fee": round(amount - refund, 2),
                "currency": details.get("currency", CURRENCY), "rule": rule}

    async def cancel(self, provider_ref: str, details: dict[str, Any],
                     amount: float) -> dict[str, Any]:
        return await self.refund_quote(details, amount)

    async def modify_quote(self, details: dict[str, Any],
                           changes: dict[str, str]) -> dict[str, Any]:
        parts = str(details["offer_id"]).split("|")
        names = PARAMS[self.kind]
        params = dict(zip(names, parts[1:-1], strict=True)) | {
            k: v for k, v in changes.items() if k in names and k in DATE_PARAMS}
        offer = GENERATORS[self.kind](params, int(parts[-1]))
        if _day(offer["start_date"]) < date.today():
            raise ProviderError("invalid_date", "The new date is in the past.")
        return offer

    async def modify(self, provider_ref: str, details: dict[str, Any],
                     changes: dict[str, str]) -> dict[str, Any]:
        return await self.modify_quote(details, changes)
