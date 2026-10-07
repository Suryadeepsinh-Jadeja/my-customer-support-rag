"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { TestBadge } from "@/components/bookings/booking-status";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api";
import { dateRange, money } from "@/lib/format";
import type { ConfirmationOut, ConfirmResponse, ConfirmationSummary } from "@/types/api";

const TITLES = { book: "Confirm booking", cancel: "Cancel booking?", modify: "Change dates?" };

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium">{children}</dd>
    </div>
  );
}

function Summary({ action, s }: { action: ConfirmationOut["action"]; s: ConfirmationSummary }) {
  if (action === "book") {
    return (
      <dl className="grid gap-2">
        <Row label="Booking">{s.title}</Row>
        <Row label="Dates">{dateRange(s.start_date ?? null, s.end_date ?? null)}</Row>
        {s.travellers?.length ? <Row label="Travellers">{s.travellers.join(", ")}</Row> : null}
        {s.previous_price !== undefined && s.currency && (
          <Row label="Previous price">
            <span className="line-through">{money(s.previous_price, s.currency)}</span>
          </Row>
        )}
        {s.price !== undefined && s.currency && <Row label="Total">{money(s.price, s.currency)}</Row>}
      </dl>
    );
  }
  const booking = s.booking;
  return (
    <dl className="grid gap-2">
      <Row label="Booking">{booking?.title}</Row>
      {booking?.confirmation_number && <Row label="Confirmation">{booking.confirmation_number}</Row>}
      {action === "cancel" && s.refund && (
        <>
          <Row label="Refund">{money(s.refund.refund_amount, s.refund.currency)}</Row>
          {s.refund.fee > 0 && <Row label="Cancellation fee">{money(s.refund.fee, s.refund.currency)}</Row>}
        </>
      )}
      {action === "modify" && s.new && (
        <>
          <Row label="New dates">{dateRange(s.new.start_date, s.new.end_date)}</Row>
          <Row label="New total">{money(s.new.price, s.new.currency)}</Row>
          {s.price_difference !== undefined && (
            <Row label="Difference">
              {s.price_difference >= 0 ? "+" : "−"}
              {money(Math.abs(s.price_difference), s.new.currency)}
            </Row>
          )}
        </>
      )}
    </dl>
  );
}

/**
 * Shows what a confirmation will do and sends the user's decision. This is the only
 * place the UI calls POST /api/chat/confirm.
 */
export function ConfirmationDialog({
  confirmation,
  open,
  onOpenChange,
  onDone,
}: {
  confirmation: ConfirmationOut;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone: (result: ConfirmResponse | null) => void;
}) {
  // One key per dialog, so a retried click can't act twice.
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [pending, setPending] = useState<"yes" | "no" | null>(null);
  const { action, summary } = confirmation;
  const test = summary.test_booking ?? summary.booking?.test_booking;

  async function decide(approved: boolean) {
    setPending(approved ? "yes" : "no");
    try {
      const result = await api<ConfirmResponse>("/chat/confirm", {
        method: "POST",
        body: { confirmation_id: confirmation.confirmation_id, approved },
        headers: { "Idempotency-Key": `${idempotencyKey}-${approved}` },
      });
      const notify = result.message.type === "ERROR" ? toast.error : toast.success;
      notify(result.message.text);
      onDone(result);
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "That didn't work. Please try again.");
      onDone(null);
      onOpenChange(false);
    } finally {
      setPending(null);
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="data-[size=default]:sm:max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            {TITLES[action]} {test && <TestBadge />}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {action === "book"
              ? "Nothing is booked until you confirm."
              : action === "cancel"
                ? "The refund is the provider's quote for cancelling now."
                : "Your booking changes only if you confirm."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <Summary action={action} s={summary} />
        <AlertDialogFooter>
          <Button variant="outline" onClick={() => decide(false)} disabled={pending !== null}>
            {pending === "no" && <Loader2 className="animate-spin" aria-hidden />}
            Decline
          </Button>
          <Button
            variant={action === "cancel" ? "destructive" : "default"}
            onClick={() => decide(true)}
            disabled={pending !== null}
          >
            {pending === "yes" && <Loader2 className="animate-spin" aria-hidden />}
            Confirm
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
