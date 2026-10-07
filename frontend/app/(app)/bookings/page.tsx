"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { BookingStatusBadge, TestBadge } from "@/components/bookings/booking-status";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { KIND, tabOf, type BookingTab } from "@/lib/bookings";
import { dateRange, money } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Booking } from "@/types/api";

const TABS: { id: BookingTab; label: string; empty: string }[] = [
  { id: "upcoming", label: "Upcoming", empty: "No upcoming trips. Ask the assistant to book one." },
  { id: "completed", label: "Completed", empty: "No completed trips yet." },
  { id: "cancelled", label: "Cancelled", empty: "Nothing cancelled." },
];

function destination(b: Booking) {
  const d = b.details as Record<string, unknown>;
  return (d.destination ?? d.city ?? d.pickup_location) as string | undefined;
}

export default function BookingsPage() {
  const [tab, setTab] = useState<BookingTab>("upcoming");
  const { data: bookings, isPending, error } = useQuery({
    queryKey: ["bookings"],
    queryFn: () => api<Booking[]>("/bookings"),
  });
  const shown = (bookings ?? [])
    .filter((b) => tabOf(b) === tab)
    .sort((a, b) =>
      tab === "upcoming"
        ? (a.start_date ?? "").localeCompare(b.start_date ?? "")
        : (b.start_date ?? "").localeCompare(a.start_date ?? ""),
    );

  return (
    <>
      <PageHeader title="Bookings" description="Flights, hotels, cars and excursions booked with the assistant." />

      <div role="tablist" aria-label="Booking status" className="mb-4 inline-flex rounded-lg bg-muted p-1">
        {TABS.map((t) => {
          const count = (bookings ?? []).filter((b) => tabOf(b) === t.id).length;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors",
                tab === t.id && "bg-background text-foreground shadow-sm",
              )}
            >
              {t.label}
              {count > 0 && <span className="ml-1.5 text-xs text-muted-foreground">{count}</span>}
            </button>
          );
        })}
      </div>

      {error ? (
        <p className="text-sm text-destructive">{error.message}</p>
      ) : isPending ? (
        <div className="grid gap-2">
          {[0, 1].map((i) => <Skeleton key={i} className="h-20 w-full" />)}
        </div>
      ) : shown.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            {TABS.find((t) => t.id === tab)?.empty}
          </CardContent>
        </Card>
      ) : (
        <ul role="tabpanel" className="grid grid-cols-1 gap-2">
          {shown.map((b) => {
            const Icon = KIND[b.kind].icon;
            const where = destination(b);
            return (
              <li key={b.id}>
                <Link
                  href={`/bookings/${b.id}`}
                  className="flex items-center gap-3 rounded-xl border bg-card p-3 transition-colors hover:bg-muted/50"
                >
                  <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-muted">
                    <Icon className="size-5 text-muted-foreground" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="truncate font-medium">{b.title}</span>
                      <BookingStatusBadge status={b.status} />
                      {b.test_booking && <TestBadge />}
                    </span>
                    <span className="block truncate text-sm text-muted-foreground">
                      {KIND[b.kind].label}
                      {where && ` · ${where}`}
                      {" · "}
                      {dateRange(b.start_date, b.end_date)}
                      {b.confirmation_number && ` · Ref ${b.confirmation_number}`}
                    </span>
                  </span>
                  <span className="hidden text-right font-medium sm:block">
                    {money(b.total_amount, b.currency)}
                  </span>
                  <ArrowRight className="size-4 text-muted-foreground" aria-hidden />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
