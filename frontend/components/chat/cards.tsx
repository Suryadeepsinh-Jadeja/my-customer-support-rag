"use client";

import { ArrowRight, BookOpen, FileText, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { BookingStatusBadge, TestBadge } from "@/components/bookings/booking-status";
import { ConfirmationDialog } from "@/components/bookings/confirmation-dialog";
import { Button } from "@/components/ui/button";
import { KIND } from "@/lib/bookings";
import { dateRange, day, duration, money, time } from "@/lib/format";
import type {
  BookingCard,
  ConfirmationCard,
  ConfirmResponse,
  Offer,
  Source,
} from "@/types/api";

// ------------------------------------------------------------------ sources

export function SourceChips({ sources }: { sources: Source[] }) {
  if (!sources.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Sources">
      {sources.map((s, i) =>
        s.type === "document" ? (
          <Link
            key={i}
            href={s.document_id ? `/documents/${s.document_id}` : "/documents"}
            className="inline-flex max-w-full items-center gap-1 rounded-full border bg-background px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <FileText className="size-3 shrink-0" aria-hidden />
            <span className="truncate">
              Based on your {s.title}
              {s.page ? `, p.${s.page}` : ""}
            </span>
          </Link>
        ) : (
          <span
            key={i}
            className="inline-flex max-w-full items-center gap-1 rounded-full border bg-background px-2 py-0.5 text-xs text-muted-foreground"
          >
            <BookOpen className="size-3 shrink-0" aria-hidden />
            <span className="truncate">
              Source: {s.title}
              {s.section ? ` · ${s.section}` : ""}
            </span>
          </span>
        ),
      )}
    </div>
  );
}

// ------------------------------------------------------------------- offers

function offerLines(o: Offer): { heading: string; lines: string[] } {
  switch (o.type) {
    case "flight_offer":
      return {
        heading: `${o.airline} ${o.flight_number}`,
        lines: [
          `${o.origin} ${time(o.departure)} → ${o.destination} ${time(o.arrival)}${o.end_date !== o.start_date ? " (+1)" : ""}`,
          `${day(o.start_date)} · ${duration(o.duration_minutes)} · ${o.stops === 0 ? "Direct" : `${o.stops} stop${o.stops > 1 ? "s" : ""}`}`,
          [o.cabin?.replace("_", " "), o.fare, o.baggage].filter(Boolean).join(" · "),
        ],
      };
    case "hotel_offer":
      return {
        heading: o.hotel_name,
        lines: [
          `${"★".repeat(o.stars)} · ${o.room_type}`,
          `${dateRange(o.start_date, o.end_date)} · ${o.nights} night${o.nights > 1 ? "s" : ""}`,
          o.refundable ? "Free cancellation" : "Non-refundable",
        ],
      };
    case "car_offer":
      return {
        heading: `${o.company} · ${o.car_class}`,
        lines: [o.model, `${o.pickup_location} · ${dateRange(o.start_date, o.end_date)} (${o.days} days)`],
      };
    case "excursion_offer":
      return {
        heading: o.title,
        lines: [`${day(o.start_date)} · ${o.duration_hours} h · ${o.participants} participant(s)`],
      };
  }
}

export function selectMessage(o: Offer) {
  return `I'd like this one: ${o.title}, ${day(o.start_date)}, ${money(o.price, o.currency)} (offer_id: ${o.offer_id})`;
}

export function OfferCard({
  offer,
  onSelect,
  disabled,
}: {
  offer: Offer;
  onSelect: (offer: Offer) => void;
  disabled?: boolean;
}) {
  const { heading, lines } = offerLines(offer);
  return (
    <div className="flex flex-col gap-3 rounded-xl border bg-card p-3 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="flex flex-wrap items-center gap-2 font-medium">
          {heading} {offer.test_booking && <TestBadge />}
        </p>
        {lines.map((line, i) => (
          <p key={i} className="text-sm text-muted-foreground">
            {line}
          </p>
        ))}
      </div>
      <div className="flex items-center justify-between gap-3 sm:flex-col sm:items-end">
        <p className="text-lg font-semibold">{money(offer.price, offer.currency)}</p>
        <Button size="sm" onClick={() => onSelect(offer)} disabled={disabled} aria-label={`Select ${heading}, ${money(offer.price, offer.currency)}`}>
          Select
        </Button>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------- bookings

export function BookingCardView({ booking }: { booking: BookingCard }) {
  const Icon = KIND[booking.kind].icon;
  return (
    <Link
      href={`/bookings/${booking.booking_id}`}
      className="flex items-center gap-3 rounded-xl border bg-card p-3 transition-colors hover:bg-muted/50"
    >
      <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-muted">
        <Icon className="size-5 text-muted-foreground" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2 font-medium">
          <span className="truncate">{booking.title}</span>
          <BookingStatusBadge status={booking.status} />
          {booking.test_booking && <TestBadge />}
        </span>
        <span className="block text-sm text-muted-foreground">
          {dateRange(booking.start_date, booking.end_date)}
          {booking.confirmation_number && ` · Ref ${booking.confirmation_number}`}
          {" · "}
          {money(booking.total_amount, booking.currency)}
          {booking.refund && ` · Refund ${money(booking.refund.refund_amount, booking.refund.currency)}`}
        </span>
      </span>
      <ArrowRight className="size-4 text-muted-foreground" aria-hidden />
    </Link>
  );
}

// ------------------------------------------------------------ confirmations

const ACTION_LABEL = { book: "Booking", cancel: "Cancellation", modify: "Date change" };

export function ConfirmationCardView({
  card,
  actionable,
  onDone,
}: {
  card: ConfirmationCard;
  actionable: boolean;
  onDone: (result: ConfirmResponse | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const s = card.summary;
  const title = s.title ?? s.booking?.title;
  const amount =
    card.action === "book" && s.price !== undefined && s.currency
      ? money(s.price, s.currency)
      : card.action === "cancel" && s.refund
        ? `Refund ${money(s.refund.refund_amount, s.refund.currency)}`
        : s.new
          ? `New total ${money(s.new.price, s.new.currency)}`
          : null;

  return (
    <div className="flex flex-col gap-3 rounded-xl border-2 border-primary/30 bg-card p-3 sm:flex-row sm:items-center">
      <ShieldCheck className="hidden size-5 shrink-0 text-primary sm:block" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {ACTION_LABEL[card.action]} awaiting your confirmation
        </p>
        <p className="font-medium">{title}</p>
        {amount && <p className="text-sm text-muted-foreground">{amount}</p>}
      </div>
      {actionable ? (
        <Button onClick={() => setOpen(true)}>Review &amp; confirm</Button>
      ) : (
        <p className="text-sm text-muted-foreground">No longer active</p>
      )}
      <ConfirmationDialog confirmation={card} open={open} onOpenChange={setOpen} onDone={onDone} />
    </div>
  );
}
