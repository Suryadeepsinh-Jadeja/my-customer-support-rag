"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarClock, Loader2, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { BookingStatusBadge, TestBadge } from "@/components/bookings/booking-status";
import { ConfirmationDialog } from "@/components/bookings/confirmation-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { ACTIVE, KIND } from "@/lib/bookings";
import { dateRange, day, duration, money, time } from "@/lib/format";
import type { Booking, ConfirmationOut } from "@/types/api";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  if (children === undefined || children === null || children === "") return null;
  return (
    <div className="grid grid-cols-[10rem_1fr] gap-2 py-1.5 text-sm max-sm:grid-cols-1 max-sm:gap-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium">{children}</dd>
    </div>
  );
}

function Details({ b }: { b: Booking }) {
  const d = b.details as Record<string, string | number | boolean | undefined>;
  const str = (k: string) => (d[k] === undefined ? undefined : String(d[k]));
  switch (b.kind) {
    case "flight":
      return (
        <>
          <Row label="Flight">{`${str("airline") ?? ""} ${str("flight_number") ?? ""}`.trim()}</Row>
          <Row label="Route">{`${str("origin")} → ${str("destination")}`}</Row>
          {typeof d.departure === "string" && typeof d.arrival === "string" && (
            <Row label="Times">{`${day(d.departure)} ${time(d.departure)} → ${time(d.arrival)}`}</Row>
          )}
          {typeof d.duration_minutes === "number" && (
            <Row label="Duration">
              {`${duration(d.duration_minutes)}, ${d.stops === 0 ? "direct" : `${d.stops} stop(s)`}`}
            </Row>
          )}
          <Row label="Cabin / fare">{[str("cabin")?.replace("_", " "), str("fare")].filter(Boolean).join(" · ")}</Row>
          <Row label="Baggage">{str("baggage")}</Row>
        </>
      );
    case "hotel":
      return (
        <>
          <Row label="Hotel">{str("hotel_name")}</Row>
          <Row label="Address">{str("address")}</Row>
          <Row label="Room">{str("room_type")}</Row>
          <Row label="Cancellation">{d.refundable ? "Free cancellation" : "Non-refundable"}</Row>
        </>
      );
    case "car":
      return (
        <>
          <Row label="Company">{str("company")}</Row>
          <Row label="Car">{`${str("car_class")} · ${str("model")}`}</Row>
          <Row label="Pick-up">{str("pickup_location")}</Row>
        </>
      );
    case "excursion":
      return (
        <>
          <Row label="City">{str("city")}</Row>
          <Row label="Duration">{d.duration_hours ? `${d.duration_hours} hours` : undefined}</Row>
          <Row label="Participants">{str("participants")}</Row>
        </>
      );
  }
}

export default function BookingPage() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [confirmation, setConfirmation] = useState<ConfirmationOut | null>(null);
  const [changing, setChanging] = useState(false);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const { data: b, isPending, error } = useQuery({
    queryKey: ["booking", id],
    queryFn: () => api<Booking>(`/bookings/${id}`),
  });

  const request = useMutation({
    mutationFn: (action: "cancel" | "modify") =>
      api<ConfirmationOut>(`/bookings/${id}/${action}`, {
        method: "POST",
        body: action === "modify" ? { start_date: start, end_date: end || null } : undefined,
      }),
    onSuccess: (c) => setConfirmation(c),
    onError: (e) => toast.error(e.message),
  });

  function done() {
    setConfirmation(null);
    setChanging(false);
    queryClient.invalidateQueries({ queryKey: ["booking", id] });
    queryClient.invalidateQueries({ queryKey: ["bookings"] });
  }

  if (error) return <p className="text-sm text-destructive">{error.message}</p>;
  if (isPending) return <Skeleton className="h-64 w-full" />;

  const Icon = KIND[b.kind].icon;
  const active = ACTIVE.includes(b.status);
  const hasEnd = b.kind === "hotel" || b.kind === "car";
  const today = new Date().toISOString().slice(0, 10);

  return (
    <>
      <Link href="/bookings" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden /> Bookings
      </Link>

      <header className="mb-6 flex items-start gap-3">
        <span className="grid size-12 shrink-0 place-items-center rounded-xl bg-muted">
          <Icon className="size-6 text-muted-foreground" aria-hidden />
        </span>
        <div className="min-w-0 space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{b.title}</h1>
          <div className="flex flex-wrap items-center gap-2">
            <BookingStatusBadge status={b.status} />
            {b.test_booking && <TestBadge />}
          </div>
        </div>
      </header>

      <div className="grid gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Details</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="divide-y">
              <Row label="Confirmation number">{b.confirmation_number ?? "–"}</Row>
              <Row label="Dates">{dateRange(b.start_date, b.end_date)}</Row>
              <Details b={b} />
              <Row label="Travellers">{b.details.travellers?.join(", ")}</Row>
              <Row label="Total">{money(b.total_amount, b.currency)}</Row>
              {b.details.modified_from && (
                <Row label="Changed from">
                  {`${day(b.details.modified_from.start_date)}, ${money(b.details.modified_from.price, b.currency)}`}
                </Row>
              )}
              {b.details.refund && (
                <Row label="Refund">
                  {money(b.details.refund.refund_amount, b.details.refund.currency)}
                  {b.details.refund.fee > 0 && ` (fee ${money(b.details.refund.fee, b.details.refund.currency)})`}
                </Row>
              )}
              <Row label="Payment">
                {b.details.payment
                  ? b.details.payment.test
                    ? `Test payment (${b.details.payment.status === "test_paid" ? "paid" : b.details.payment.status})`
                    : b.details.payment.status
                  : undefined}
              </Row>
              <Row label="Provider">{b.test_booking ? `${b.provider} (test)` : b.provider}</Row>
              <Row label="Booked">{new Date(b.created_at).toLocaleString()}</Row>
            </dl>
          </CardContent>
        </Card>

        {active && (
          <Card>
            <CardHeader>
              <CardTitle>Manage</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              {changing ? (
                <form
                  className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
                  onSubmit={(e) => {
                    e.preventDefault();
                    request.mutate("modify");
                  }}
                >
                  <div className="grid gap-1.5">
                    <Label htmlFor="start">{hasEnd ? "New start date" : "New date"}</Label>
                    <Input id="start" type="date" min={today} required value={start} onChange={(e) => setStart(e.target.value)} />
                  </div>
                  {hasEnd && (
                    <div className="grid gap-1.5">
                      <Label htmlFor="end">New end date (optional)</Label>
                      <Input id="end" type="date" min={start || today} value={end} onChange={(e) => setEnd(e.target.value)} />
                    </div>
                  )}
                  <div className="flex gap-2">
                    <Button type="submit" disabled={!start || request.isPending}>
                      {request.isPending && <Loader2 className="animate-spin" aria-hidden />}
                      Get new price
                    </Button>
                    <Button type="button" variant="ghost" onClick={() => setChanging(false)}>
                      Back
                    </Button>
                  </div>
                </form>
              ) : (
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" onClick={() => setChanging(true)}>
                    <CalendarClock aria-hidden /> Change dates
                  </Button>
                  <Button variant="destructive" onClick={() => request.mutate("cancel")} disabled={request.isPending}>
                    {request.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <XCircle aria-hidden />}
                    Cancel booking
                  </Button>
                </div>
              )}
              <p className="text-sm text-muted-foreground">
                You&apos;ll see the price or refund first. Nothing changes until you confirm.
              </p>
            </CardContent>
          </Card>
        )}
      </div>

      {confirmation && (
        <ConfirmationDialog
          key={confirmation.confirmation_id}
          confirmation={confirmation}
          open
          onOpenChange={(open) => !open && setConfirmation(null)}
          onDone={done}
        />
      )}
    </>
  );
}
