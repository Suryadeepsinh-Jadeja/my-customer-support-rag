import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";

import { cn } from "@/lib/utils";
import { isInFlight, STATUS, steps } from "@/lib/documents";
import type { DocumentStatus, TravelDocument } from "@/types/api";

const TONES = {
  muted: "bg-muted text-muted-foreground",
  info: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  ok: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  bad: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const { label, tone } = STATUS[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        TONES[tone],
      )}
    >
      {(status === "queued" || status === "processing") && (
        <Loader2 className="size-3 animate-spin" aria-hidden />
      )}
      {label}
    </span>
  );
}

/** Checklist of pipeline steps: ✓ done, spinner for the step in progress, ✗ where it failed. */
export function ProcessingSteps({ doc }: { doc: TravelDocument }) {
  const list = steps(doc);
  const firstPending = list.findIndex((s) => !s.done);
  const failed = doc.status === "failed" || doc.status === "rejected";

  return (
    <ol className="grid gap-1.5 text-sm" aria-label="Processing steps">
      {list.map((step, i) => {
        const active = i === firstPending;
        let icon = <Circle className="size-4 text-muted-foreground/60" aria-hidden />;
        let state = "pending";
        if (step.done) {
          icon = <CheckCircle2 className="size-4 text-emerald-600" aria-hidden />;
          state = "done";
        } else if (active && failed) {
          icon = <XCircle className="size-4 text-destructive" aria-hidden />;
          state = "failed";
        } else if (active && isInFlight(doc)) {
          icon = <Loader2 className="size-4 animate-spin text-sky-600" aria-hidden />;
          state = "in progress";
        }
        return (
          <li key={step.label} className="flex items-center gap-2">
            {icon}
            <span className={cn(!step.done && "text-muted-foreground")}>
              {step.label}
              <span className="sr-only"> ({state})</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
