import { STATUS, TONES } from "@/lib/bookings";
import { cn } from "@/lib/utils";
import type { BookingStatus } from "@/types/api";

export function BookingStatusBadge({ status }: { status: BookingStatus }) {
  const { label, tone } = STATUS[status];
  return (
    <span className={cn("inline-flex rounded-full px-2 py-0.5 text-xs font-medium uppercase", TONES[tone])}>
      {label}
    </span>
  );
}

export function TestBadge() {
  return (
    <span className="inline-flex rounded-full border border-dashed border-amber-500/60 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400">
      Test booking
    </span>
  );
}
