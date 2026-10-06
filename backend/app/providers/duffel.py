"""Duffel flights adapter (https://duffel.com/docs/api, API version v2).

Use a `duffel_test_...` key for Duffel's test mode (sandbox airline "Duffel Airways",
no real tickets). Flow: offer request -> offers; the offer is fetched again for the
current price before booking; an instant order is paid from the Duffel balance.
Cancellations are quoted with an order cancellation and confirmed on approval.

Searches are for one adult; date changes aren't supported online.
"""

import re
from datetime import datetime
from typing import Any

import httpx

from app.providers.base import BookingProvider, ProviderError

API_VERSION = "v2"
OFFERS_SHOWN = 5

MESSAGES = {
    "offer_no_longer_available": "That flight is no longer available. Please search again.",
    "offer_request_already_booked": "That offer has already been booked.",
    "already_cancelled": "This booking was already cancelled.",
    "not_found": "The flight provider couldn't find that.",
    "rate_limit_exceeded": "The flight provider is busy. Please try again in a minute.",
}


def _minutes(iso_duration: str | None) -> int | None:
    match = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?", iso_duration or "")
    if not match or not any(match.groups()):
        return None
    days, hours, minutes = (int(g or 0) for g in match.groups())
    return days * 1440 + hours * 60 + minutes


def map_offer(o: dict[str, Any]) -> dict[str, Any]:
    """A Duffel offer as the app's flight offer dict (first slice only)."""
    slice_ = o["slices"][0]
    segments = slice_["segments"]
    first, last = segments[0], segments[-1]
    carrier = first.get("marketing_carrier") or o.get("owner") or {}
    number = f"{carrier.get('iata_code', '')}{first.get('marketing_carrier_flight_number', '')}"
    origin = slice_["origin"]["iata_code"]
    destination = slice_["destination"]["iata_code"]
    departure, arrival = first["departing_at"], last["arriving_at"]
    duration = _minutes(slice_.get("duration")) or round(
        (datetime.fromisoformat(arrival) - datetime.fromisoformat(departure)).total_seconds()
        / 60)
    passenger = (first.get("passengers") or [{}])[0]
    checked = sum(b.get("quantity", 0) for b in passenger.get("baggages", [])
                  if b.get("type") == "checked")
    refund = (o.get("conditions") or {}).get("refund_before_departure") or {}
    return {
        "offer_id": o["id"], "kind": "flight", "provider": "duffel",
        "test_booking": not o.get("live_mode", False),
        "title": f"{carrier.get('name', 'Flight')} {number} {origin}-{destination}",
        "price": float(o["total_amount"]), "currency": o["total_currency"],
        "start_date": departure[:10], "end_date": arrival[:10],
        "airline": carrier.get("name"), "flight_number": number, "origin": origin,
        "destination": destination, "departure": departure[:16], "arrival": arrival[:16],
        "duration_minutes": duration, "stops": len(segments) - 1,
        "cabin": passenger.get("cabin_class"), "fare": slice_.get("fare_brand_name") or "",
        "baggage": f"{checked} checked bag(s)" if checked else "Hand baggage only",
        "refundable": bool(refund.get("allowed")), "expires_at": o.get("expires_at"),
        "passenger_ids": [p["id"] for p in o.get("passengers", [])],
    }


def _passenger(passenger_id: str, traveller: dict[str, Any],
               contact: dict[str, Any]) -> dict[str, Any]:
    if not traveller.get("born_on") or traveller.get("gender") not in {"m", "f"}:
        raise ProviderError(
            "passenger_details_missing",
            "Booking this flight needs each traveller's date of birth and gender. Upload "
            "their passport first.")
    if not contact.get("phone"):
        raise ProviderError("contact_missing",
                            "Add a phone number to your profile to book this flight.")
    names = traveller["name"].split()
    return {
        "id": passenger_id, "given_name": " ".join(names[:-1]) or names[0],
        "family_name": names[-1], "born_on": traveller["born_on"],
        "gender": traveller["gender"], "title": "ms" if traveller["gender"] == "f" else "mr",
        "email": contact["email"],
        "phone_number": re.sub(r"[^\d+]", "", contact["phone"]),  # E.164, no spaces
    }


class DuffelProvider(BookingProvider):
    name = "duffel"

    def __init__(self, api_key: str, base_url: str = "https://api.duffel.com",
                 transport: httpx.AsyncBaseTransport | None = None, timeout: float = 30):
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=timeout, transport=transport,
            headers={"Authorization": f"Bearer {api_key}", "Duffel-Version": API_VERSION,
                     "Accept": "application/json", "Content-Type": "application/json"})

    async def _request(self, method: str, path: str,
                       body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method, path, json={"data": body} if body is not None else None)
        except httpx.HTTPError as exc:
            raise ProviderError("provider_unavailable",
                                "The flight provider can't be reached right now.") from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            errors = payload.get("errors") or [{}]
            code = errors[0].get("code") or f"http_{response.status_code}"
            raise ProviderError(code, MESSAGES.get(
                code, "The flight provider couldn't complete that request."))
        return payload["data"]

    async def search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        data = await self._request("POST", "/air/offer_requests?return_offers=true", {
            "slices": [{"origin": params["origin"], "destination": params["destination"],
                        "departure_date": params["date"]}],
            "passengers": [{"type": "adult"}],
            "cabin_class": params["cabin"],
        })
        offers = sorted(data.get("offers", []), key=lambda o: float(o["total_amount"]))
        return [map_offer(o) for o in offers[:OFFERS_SHOWN]]

    async def get_offer(self, offer_id: str) -> dict[str, Any]:
        gone = ProviderError("offer_not_found", "That offer no longer exists. Search again.")
        if not re.fullmatch(r"off_[A-Za-z0-9]+", offer_id):
            raise gone
        try:
            return map_offer(await self._request("GET", f"/air/offers/{offer_id}"))
        except ProviderError as exc:
            if exc.code == "not_found":
                raise gone from exc
            raise

    async def book(self, offer: dict[str, Any], travellers: list[dict[str, Any]],
                   contact: dict[str, Any]) -> dict[str, Any]:
        ids = offer["passenger_ids"]
        if len(travellers) != len(ids):
            raise ProviderError("passenger_count",
                                f"This offer is for {len(ids)} traveller(s).")
        order = await self._request("POST", "/air/orders", {
            "type": "instant",
            "selected_offers": [offer["offer_id"]],
            "passengers": [_passenger(i, t, contact) for i, t in zip(ids, travellers,
                                                                     strict=True)],
            "payments": [{"type": "balance", "currency": offer["currency"],
                          "amount": f"{offer['price']:.2f}"}],
        })
        return {"reference": order["booking_reference"], "order_id": order["id"]}

    async def _cancellation(self, details: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/air/order_cancellations",
                                   {"order_id": details["order_id"]})

    @staticmethod
    def _refund(c: dict[str, Any], amount: float) -> dict[str, Any]:
        refund = float(c.get("refund_amount") or 0)
        return {"refund_amount": round(refund, 2), "fee": round(max(0.0, amount - refund), 2),
                "currency": c.get("refund_currency"), "rule": "provider"}

    async def refund_quote(self, details: dict[str, Any], amount: float) -> dict[str, Any]:
        return self._refund(await self._cancellation(details), amount)

    async def cancel(self, provider_ref: str, details: dict[str, Any],
                     amount: float) -> dict[str, Any]:
        quote = await self._cancellation(details)
        confirmed = await self._request(
            "POST", f"/air/order_cancellations/{quote['id']}/actions/confirm")
        return self._refund(confirmed, amount)

    async def modify_quote(self, details: dict[str, Any],
                           changes: dict[str, str]) -> dict[str, Any]:
        raise ProviderError("not_supported", "Changing the date of this flight isn't "
                            "supported online. Cancel and rebook, or contact the airline.")

    async def modify(self, provider_ref: str, details: dict[str, Any],
                     changes: dict[str, str]) -> dict[str, Any]:
        return await self.modify_quote(details, changes)
