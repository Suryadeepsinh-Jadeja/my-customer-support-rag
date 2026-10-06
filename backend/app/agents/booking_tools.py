"""Search and booking tools for the assistant.

Searches return offers (also shown to the user as cards). The book/cancel/modify tools
never act: they create a confirmation request the user must approve in the UI, and tell
the model that nothing has happened yet.
"""

import datetime as dt
import uuid
from typing import Annotated, Any

from pydantic import Field, StringConstraints
from sqlalchemy import select

from app.agents.tools import ToolArgs, ToolContext, tool
from app.db.models import (
    BookingKind,
    CabinClass,
    ConfirmationRequest,
    Document,
    DocumentType,
    ExtractedEntity,
)
from app.providers import ProviderError
from app.services.booking_service import BookingService, booking_card, confirmation_card

Iata = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{3}$", to_upper=True)]
Place = Annotated[str, StringConstraints(min_length=2, max_length=60, strip_whitespace=True)]

PENDING_NOTE = ("Nothing has been booked or changed yet. Show the user this summary and ask "
                "them to press Confirm or Decline on the confirmation card. A typed 'yes' "
                "doesn't confirm.")


def _not_past(*days: dt.date) -> None:
    if any(d < dt.date.today() for d in days):
        raise ProviderError("invalid_date", "That date is in the past.")


def _offer_cards(ctx: ToolContext, offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ctx.cards.extend({"type": f"{o['kind']}_offer", **o} for o in offers)
    return [{k: v for k, v in o.items() if k not in {"kind", "provider", "refund_rule"}}
            for o in offers]


# ---------------------------------------------------------------- searches


class FlightSearchArgs(ToolArgs):
    origin: Iata = Field(description="Departure airport IATA code, e.g. BOM")
    destination: Iata = Field(description="Arrival airport IATA code, e.g. LHR")
    date: dt.date = Field(description="Departure date, YYYY-MM-DD")
    cabin: CabinClass | None = Field(default=None,
                                     description="Cabin; defaults to the user's preference")


@tool("search_flights",
      "Search flights for one direction on one date. Returns offers with offer_id, airline, "
      "flight number, times, duration, stops, cabin, fare, baggage and price. Results are "
      "test inventory from a mock provider.", FlightSearchArgs)
async def search_flights(ctx: ToolContext, args: FlightSearchArgs) -> dict[str, Any]:
    _not_past(args.date)
    prefs = ctx.user.preferences
    cabin = args.cabin or (prefs.preferred_cabin if prefs else None) or CabinClass.ECONOMY
    offers = await BookingService(ctx.session, ctx.user).search(BookingKind.FLIGHT, {
        "origin": args.origin, "destination": args.destination,
        "date": args.date.isoformat(), "cabin": cabin.value})
    # Preferred airlines first, then cheapest; an explicit request overrides preferences.
    preferred = {a.upper() for a in (prefs.preferred_airlines if prefs else [])}
    offers.sort(key=lambda o: (o["flight_number"][:2] not in preferred, o["price"]))
    return {"cabin": cabin.value, "offers": _offer_cards(ctx, offers)}


class HotelSearchArgs(ToolArgs):
    city: Place
    check_in: dt.date
    check_out: dt.date
    guests: int = Field(default=1, ge=1, le=8)


@tool("search_hotels", "Search hotels in a city for given dates (test inventory).",
      HotelSearchArgs)
async def search_hotels(ctx: ToolContext, args: HotelSearchArgs) -> dict[str, Any]:
    _not_past(args.check_in)
    offers = await BookingService(ctx.session, ctx.user).search(BookingKind.HOTEL, {
        "city": args.city, "check_in": args.check_in.isoformat(),
        "check_out": args.check_out.isoformat(), "guests": args.guests})
    return {"offers": _offer_cards(ctx, sorted(offers, key=lambda o: o["price"]))}


class CarSearchArgs(ToolArgs):
    location: Place = Field(description="City or airport code where the car is picked up")
    pickup_date: dt.date
    dropoff_date: dt.date


@tool("search_cars", "Search rental cars (test inventory).", CarSearchArgs)
async def search_cars(ctx: ToolContext, args: CarSearchArgs) -> dict[str, Any]:
    _not_past(args.pickup_date)
    offers = await BookingService(ctx.session, ctx.user).search(BookingKind.CAR, {
        "location": args.location, "pickup_date": args.pickup_date.isoformat(),
        "dropoff_date": args.dropoff_date.isoformat()})
    return {"offers": _offer_cards(ctx, sorted(offers, key=lambda o: o["price"]))}


class ExcursionSearchArgs(ToolArgs):
    city: Place
    date: dt.date
    participants: int = Field(default=1, ge=1, le=10)


@tool("search_excursions", "Search excursions and tours (test inventory).",
      ExcursionSearchArgs)
async def search_excursions(ctx: ToolContext, args: ExcursionSearchArgs) -> dict[str, Any]:
    _not_past(args.date)
    offers = await BookingService(ctx.session, ctx.user).search(BookingKind.EXCURSION, {
        "city": args.city, "date": args.date.isoformat(), "participants": args.participants})
    return {"offers": _offer_cards(ctx, offers)}


# ------------------------------------------------------------- bookings


class BookingsArgs(ToolArgs):
    kind: BookingKind | None = None


@tool("get_bookings",
      "The user's bookings made through this assistant (flights, hotels, cars, excursions) "
      "with status, dates, price and confirmation number.", BookingsArgs)
async def get_bookings(ctx: ToolContext, args: BookingsArgs) -> dict[str, Any]:
    bookings = await BookingService(ctx.session, ctx.user).bookings(args.kind)
    cards = [booking_card(b) for b in bookings]
    ctx.cards.extend(cards)
    return {"bookings": cards}


async def _traveller(ctx: ToolContext) -> str | None:
    """The passport name if there is one, else the profile name."""
    name = (await ctx.session.execute(
        select(ExtractedEntity.value)
        .join(Document, Document.id == ExtractedEntity.document_id)
        .where(ExtractedEntity.user_id == ctx.user.id, Document.user_id == ctx.user.id,
               Document.document_type == DocumentType.PASSPORT,
               ExtractedEntity.field == "full_name")
        .order_by(Document.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    return name or (ctx.user.profile.full_name if ctx.user.profile else None) or None


def _pending(ctx: ToolContext, confirmation: ConfirmationRequest) -> dict[str, Any]:
    card = confirmation_card(confirmation)
    ctx.cards.append(card)
    summary = {k: v for k, v in confirmation.summary.items() if k != "offer"}
    return {"status": "awaiting_user_confirmation", "summary": summary, "note": PENDING_NOTE}


class BookArgs(ToolArgs):
    offer_id: str = Field(min_length=3, max_length=200,
                          description="offer_id from a search result")
    travellers: list[Annotated[str, StringConstraints(min_length=2, max_length=100)]] | None = (
        Field(default=None, max_length=9,
              description="Traveller full names; omit to use the user's passport/profile name"))


def _register_book(kind: BookingKind) -> None:
    async def book(ctx: ToolContext, args: BookArgs) -> dict[str, Any]:
        if not args.offer_id.startswith(f"{kind.value}|"):
            raise ProviderError("offer_not_found", f"That isn't a {kind.value} offer.")
        travellers = args.travellers or [n for n in [await _traveller(ctx)] if n]
        if not travellers:
            return {"error": "No traveller name is known. Ask the user for the full name "
                             "as shown in their passport."}
        confirmation = await BookingService(ctx.session, ctx.user).propose_booking(
            kind, args.offer_id, travellers, ctx.conversation_id)
        return _pending(ctx, confirmation)

    tool(f"book_{kind.value}",
         f"Prepare a {kind.value} booking from a search offer. This does NOT book: it shows "
         "the user a confirmation card they must approve.", BookArgs,
         requires_confirmation=True, requires_payment=True, reversible=False)(book)


for _kind in BookingKind:
    _register_book(_kind)


class BookingIdArgs(ToolArgs):
    booking_id: uuid.UUID = Field(description="booking_id from get_bookings")


@tool("cancel_booking",
      "Prepare the cancellation of a booking. Returns the provider's refund quote and "
      "shows the user a confirmation card; nothing is cancelled until they approve.",
      BookingIdArgs, requires_confirmation=True, reversible=False)
async def cancel_booking(ctx: ToolContext, args: BookingIdArgs) -> dict[str, Any]:
    confirmation = await BookingService(ctx.session, ctx.user).propose_cancel(
        args.booking_id, ctx.conversation_id)
    return _pending(ctx, confirmation)


class ModifyArgs(BookingIdArgs):
    new_start_date: dt.date = Field(description="New flight/excursion date, hotel check-in "
                                             "or car pick-up date")
    new_end_date: dt.date | None = Field(default=None, description="New check-out or drop-off "
                                      "date; omit to keep the same length")


@tool("modify_booking",
      "Prepare a date change for a booking. Shows the new price and a confirmation card; "
      "nothing changes until the user approves.", ModifyArgs,
      requires_confirmation=True, requires_payment=True)
async def modify_booking(ctx: ToolContext, args: ModifyArgs) -> dict[str, Any]:
    _not_past(args.new_start_date)
    confirmation = await BookingService(ctx.session, ctx.user).propose_modify(
        args.booking_id, args.new_start_date, args.new_end_date, ctx.conversation_id)
    return _pending(ctx, confirmation)
