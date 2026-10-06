"""Consistency checks across the user's travel documents. Plain code, no LLM.

Works on extracted fields, which are evidence rather than verified truth, so findings are
phrased as things to double-check.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

PASSPORT_VALIDITY_MONTHS = 6
FLIGHT_TYPES = {"flight_ticket", "itinerary", "boarding_pass"}


@dataclass
class DocFields:
    filename: str
    document_type: str | None
    # (field, value, segment) as extracted
    fields: list[tuple[str, str, int]] = field(default_factory=list)

    def first(self, name: str) -> str | None:
        return next((v for f, v, _ in self.fields if f == name), None)

    def segments(self) -> dict[int, dict[str, str]]:
        out: dict[int, dict[str, str]] = {}
        for f, v, seg in self.fields:
            out.setdefault(seg, {})[f] = v
        return out


@dataclass
class Issue:
    kind: str       # name_mismatch | passport_expiry | hotel_dates | same_day_flights
    severity: str   # warning | error
    message: str
    documents: list[str]


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _name_tokens(name: str) -> set[str]:
    return set(re.findall(r"[A-Z]+", name.upper())) - {"MR", "MRS", "MS", "MISS", "DR"}


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year, month = d.year + month // 12, month % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


@dataclass
class _Flight:
    filename: str
    label: str
    departure: date | None
    arrival: date | None


def _flights(docs: list[DocFields]) -> list[_Flight]:
    flights = []
    for doc in docs:
        if doc.document_type not in FLIGHT_TYPES:
            continue
        for seg in doc.segments().values():
            dep = _date(seg.get("departure_date"))
            if dep is None:
                continue
            route = "-".join(x for x in (seg.get("departure_airport"),
                                         seg.get("arrival_airport")) if x)
            label = " ".join(x for x in (seg.get("flight_number"), route) if x) or "a flight"
            flights.append(_Flight(doc.filename, label, dep,
                                   _date(seg.get("arrival_date")) or dep))
    return flights


def check(docs: list[DocFields], today: date) -> list[Issue]:
    issues: list[Issue] = []
    passports = [d for d in docs if d.document_type == "passport"]
    flights = _flights(docs)

    # 1. Passenger name on tickets vs the passport name.
    for doc in docs:
        if doc.document_type not in FLIGHT_TYPES or not doc.first("passenger_name"):
            continue
        passenger = doc.first("passenger_name") or ""
        for passport in passports:
            holder = passport.first("full_name")
            if holder and _name_tokens(passenger) != _name_tokens(holder):
                issues.append(Issue(
                    "name_mismatch", "warning",
                    f"The passenger name on {doc.filename} ({passenger}) doesn't exactly match "
                    f"the name on {passport.filename} ({holder}). Names on tickets must match "
                    "the travel document.", [doc.filename, passport.filename]))

    # 2. Passport validity: expired, or less than 6 months left at a travel date.
    for passport in passports:
        expiry = _date(passport.first("expiry_date"))
        if expiry is None:
            continue
        if expiry < today:
            issues.append(Issue("passport_expiry", "error",
                                f"The passport in {passport.filename} expired on {expiry}.",
                                [passport.filename]))
            continue
        for flight in flights:
            if flight.departure is None or flight.departure < today:
                continue
            if expiry < _add_months(flight.departure, PASSPORT_VALIDITY_MONTHS):
                issues.append(Issue(
                    "passport_expiry", "error" if expiry < flight.departure else "warning",
                    f"The passport in {passport.filename} expires on {expiry}, less than "
                    f"{PASSPORT_VALIDITY_MONTHS} months after {flight.label} on "
                    f"{flight.departure}. Many countries require six months' validity.",
                    [passport.filename, flight.filename]))

    # 3. Hotel stays that don't line up with any flight date.
    if flights:
        travel_days = {d for f in flights for d in (f.departure, f.arrival) if d}
        for doc in docs:
            if doc.document_type != "hotel_booking":
                continue
            check_in, check_out = _date(doc.first("check_in")), _date(doc.first("check_out"))
            if check_in is None or check_out is None:
                continue
            window = (check_in - timedelta(days=1), check_out + timedelta(days=1))
            if not any(window[0] <= d <= window[1] for d in travel_days):
                issues.append(Issue(
                    "hotel_dates", "warning",
                    f"The hotel stay in {doc.filename} ({check_in} to {check_out}) doesn't "
                    "match any of your flight dates.", [doc.filename]))

    # 4. Two different tickets departing on the same day.
    seen: dict[date, _Flight] = {}
    for flight in flights:
        if flight.departure is None:
            continue
        other = seen.get(flight.departure)
        if other and other.filename != flight.filename:
            issues.append(Issue(
                "same_day_flights", "warning",
                f"{other.filename} ({other.label}) and {flight.filename} ({flight.label}) both "
                f"depart on {flight.departure}. Check this is intended.",
                [other.filename, flight.filename]))
        seen.setdefault(flight.departure, flight)

    return issues
