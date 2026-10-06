import { BedDouble, Car, MapPinned, Plane, type LucideIcon } from "lucide-react";

import type { Booking, BookingKind, BookingStatus } from "@/types/api";

export const KIND: Record<BookingKind, { label: string; icon: LucideIcon }> = {
  flight: { label: "Flight", icon: Plane },
  hotel: { label: "Hotel", icon: BedDouble },
  car: { label: "Car rental", icon: Car },
  excursion: { label: "Excursion", icon: MapPinned },
};

type Tone = "ok" | "info" | "muted" | "bad";

export const STATUS: Record<BookingStatus, { label: string; tone: Tone }> = {
  booking: { label: "Pending", tone: "info" },
  confirmed: { label: "Confirmed", tone: "ok" },
  modification_requested: { label: "Pending", tone: "info" },
  modified: { label: "Confirmed", tone: "ok" },
  cancellation_requested: { label: "Pending", tone: "info" },
  cancelled: { label: "Cancelled", tone: "muted" },
  failed: { label: "Failed", tone: "bad" },
  expired: { label: "Expired", tone: "muted" },
};

export const TONES: Record<Tone, string> = {
  muted: "bg-muted text-muted-foreground",
  info: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  ok: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  bad: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

export const ACTIVE: BookingStatus[] = ["confirmed", "modified"];

export type BookingTab = "upcoming" | "completed" | "cancelled";

export function tabOf(b: Pick<Booking, "status" | "start_date">): BookingTab {
  if (b.status === "cancelled" || b.status === "failed" || b.status === "expired") {
    return "cancelled";
  }
  const today = new Date().toISOString().slice(0, 10);
  return b.start_date && b.start_date < today ? "completed" : "upcoming";
}
