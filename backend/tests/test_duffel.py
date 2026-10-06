"""Duffel adapter mapping and requests, against recorded sandbox responses (no network)."""

import json

import httpx
import pytest

from app.core.config import get_settings
from app.providers import ProviderError, get_provider
from app.providers.duffel import DuffelProvider, map_offer
from tests import duffel_fixtures as fx

TRAVELLER = {"name": "Asha Mehta", "born_on": "1990-04-02", "gender": "f"}
CONTACT = {"email": "asha.test@example.com", "phone": "+442080160508"}
SEARCH = {"origin": "LHR", "destination": "JFK", "date": "2026-11-20", "cabin": "economy"}


def provider(routes: dict[tuple[str, str], tuple[int, dict]], seen: list | None = None):
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        status, body = routes[(request.method, request.url.path)]
        return httpx.Response(status, json=body)

    return DuffelProvider("duffel_test_abc", transport=httpx.MockTransport(handle))


def test_offer_mapping():
    direct = map_offer(fx.DIRECT)
    assert direct == direct | {
        "offer_id": fx.DIRECT["id"], "provider": "duffel", "test_booking": True,
        "title": "Duffel Airways ZZ3829 LHR-JFK", "price": 224.41, "currency": "USD",
        "start_date": "2026-11-20", "departure": "2026-11-20T14:42",
        "arrival": "2026-11-20T17:40", "duration_minutes": 478, "stops": 0,
        "cabin": "economy", "fare": "Basic", "baggage": "1 checked bag(s)",
        "refundable": False, "passenger_ids": [fx.PASSENGER_ID],
    }
    connecting = map_offer(fx.CONNECTING)
    assert connecting["title"] == "SWISS LX0317 LHR-JFK"  # marketing carrier, not owner
    assert (connecting["stops"], connecting["duration_minutes"]) == (1, 760)
    assert connecting["baggage"] == "Hand baggage only"


async def test_search_sends_an_offer_request_and_sorts_by_price():
    seen: list[httpx.Request] = []
    p = provider({("POST", "/air/offer_requests"): (201, fx.OFFER_REQUEST)}, seen)
    offers = await p.search(SEARCH)
    assert [o["flight_number"] for o in offers] == ["ZZ3829", "LX0317"]

    request = seen[0]
    assert request.url.params["return_offers"] == "true"
    assert request.headers["Authorization"] == "Bearer duffel_test_abc"
    assert request.headers["Duffel-Version"] == "v2"
    assert json.loads(request.content) == {"data": {
        "slices": [{"origin": "LHR", "destination": "JFK", "departure_date": "2026-11-20"}],
        "passengers": [{"type": "adult"}], "cabin_class": "economy"}}


async def test_offer_lookup_and_errors():
    p = provider({
        ("GET", f"/air/offers/{fx.DIRECT['id']}"): (200, fx.OFFER),
        ("GET", "/air/offers/off_0000AAAAAAAAAAAAAAAAAAAA"): (404, fx.NOT_FOUND),
    })
    assert (await p.get_offer(fx.DIRECT["id"]))["price"] == 224.41
    with pytest.raises(ProviderError) as gone:
        await p.get_offer("off_0000AAAAAAAAAAAAAAAAAAAA")
    assert gone.value.code == "offer_not_found"
    assert gone.value.message == "That offer no longer exists. Search again."
    with pytest.raises(ProviderError) as bad:
        await p.get_offer("flight|BOM|LHR|2026-10-20|economy|0")  # a mock id
    assert bad.value.code == "offer_not_found"


async def test_network_failures_become_provider_errors():
    def fail(request):
        raise httpx.ConnectError("down")

    p = DuffelProvider("duffel_test_abc", transport=httpx.MockTransport(fail))
    with pytest.raises(ProviderError) as exc:
        await p.search(SEARCH)
    assert exc.value.code == "provider_unavailable"


async def test_order_creation():
    seen: list[httpx.Request] = []
    p = provider({("POST", "/air/orders"): (201, fx.ORDER)}, seen)
    offer = map_offer(fx.OFFER["data"])
    assert await p.book(offer, [TRAVELLER], CONTACT) == {
        "reference": "JPZ3RG", "order_id": fx.ORDER["data"]["id"]}
    assert json.loads(seen[0].content)["data"] == {
        "type": "instant", "selected_offers": [fx.DIRECT["id"]],
        "passengers": [{"id": fx.PASSENGER_ID, "given_name": "Asha", "family_name": "Mehta",
                        "born_on": "1990-04-02", "gender": "f", "title": "ms",
                        "email": "asha.test@example.com", "phone_number": "+442080160508"}],
        "payments": [{"type": "balance", "currency": "USD", "amount": "224.41"}],
    }


@pytest.mark.parametrize(("traveller", "contact", "code"), [
    ({"name": "Asha Mehta"}, CONTACT, "passenger_details_missing"),
    (TRAVELLER, {"email": "asha@example.com", "phone": None}, "contact_missing"),
])
async def test_order_needs_passenger_details(traveller, contact, code):
    p = provider({})
    with pytest.raises(ProviderError) as exc:
        await p.book(map_offer(fx.DIRECT), [traveller], contact)
    assert exc.value.code == code
    with pytest.raises(ProviderError) as count:
        await p.book(map_offer(fx.DIRECT), [TRAVELLER, TRAVELLER], CONTACT)
    assert count.value.code == "passenger_count"


async def test_cancellation_is_quoted_then_confirmed():
    seen: list[httpx.Request] = []
    quote_id = fx.ORDER_CANCELLATION["data"]["id"]
    p = provider({
        ("POST", "/air/order_cancellations"): (201, fx.ORDER_CANCELLATION),
        ("POST", f"/air/order_cancellations/{quote_id}/actions/confirm"):
            (200, fx.ORDER_CANCELLATION_CONFIRMED),
    }, seen)
    details = {"order_id": fx.ORDER["data"]["id"]}
    quote = await p.refund_quote(details, 224.41)
    assert quote == {"refund_amount": 224.41, "fee": 0.0, "currency": "USD",
                     "rule": "provider"}
    assert await p.cancel("JPZ3RG", details, 224.41) == quote
    assert json.loads(seen[0].content) == {"data": {"order_id": details["order_id"]}}
    assert seen[-1].url.path.endswith("/actions/confirm")
    with pytest.raises(ProviderError) as exc:
        await p.modify_quote(details, {"date": "2026-11-21"})
    assert exc.value.code == "not_supported"


def test_provider_selection(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "FLIGHT_PROVIDER", "mock")
    assert get_provider("flight").name == "mock"
    monkeypatch.setattr(settings, "FLIGHT_PROVIDER", "duffel")
    monkeypatch.setattr(settings, "DUFFEL_API_KEY", "")
    with pytest.raises(ProviderError):
        get_provider("flight")  # no key
    monkeypatch.setattr(settings, "DUFFEL_API_KEY", "duffel_test_abc")
    assert get_provider("flight").name == "duffel"
    assert get_provider("hotel").name == "mock"
