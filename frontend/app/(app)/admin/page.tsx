"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, RefreshCw, XCircle } from "lucide-react";

import { BookingStatusBadge } from "@/components/bookings/booking-status";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api } from "@/lib/api";
import { money } from "@/lib/format";
import type { AdminOverview } from "@/types/api";

function when(iso: string | null) {
  return iso ? new Date(iso).toLocaleString() : "–";
}

function Table({ head, rows, empty }: { head: string[]; rows: React.ReactNode[][]; empty: string }) {
  if (!rows.length) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-max text-left text-sm">
        <thead className="text-xs uppercase text-muted-foreground">
          <tr>
            {head.map((h) => (
              <th key={h} className="py-2 pr-4 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} className="py-2 pr-4 align-top">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Section({ title, description, children }: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export default function AdminPage() {
  const { data, error, isPending, refetch, isFetching } = useQuery({
    queryKey: ["admin-overview"],
    queryFn: () => api<AdminOverview>("/admin/overview"),
  });

  if (error) {
    const forbidden = error instanceof ApiError && error.status === 403;
    return (
      <>
        <PageHeader title="Admin" />
        <p className="text-sm text-destructive">
          {forbidden ? "This page is for administrators only." : error.message}
        </p>
      </>
    );
  }

  return (
    <>
      <div className="flex items-start justify-between gap-4">
        <PageHeader
          title="Admin"
          description="System health and activity. Document contents and personal identifiers are never shown here."
        />
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw className={isFetching ? "animate-spin" : ""} aria-hidden /> Refresh
        </Button>
      </div>

      {isPending ? (
        <div className="grid gap-4">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-40 w-full" />)}
        </div>
      ) : (
        <div className="grid gap-4">
          <Section title="Health" description={`Readiness: ${data.ready.status.replace("_", " ")}`}>
            <ul className="grid gap-2 sm:grid-cols-2">
              {Object.entries(data.ready.checks).map(([name, check]) => (
                <li key={name} className="flex items-center gap-2 text-sm">
                  {check.ok ? (
                    <CheckCircle2 className="size-4 text-emerald-600" aria-label="OK" />
                  ) : (
                    <XCircle className="size-4 text-destructive" aria-label="Failing" />
                  )}
                  <span className="font-medium">{name.replace("_", " ")}</span>
                  <span className="truncate text-muted-foreground">
                    {Object.entries(check)
                      .filter(([k]) => k !== "ok")
                      .map(([k, v]) => `${k}: ${String(v)}`)
                      .join(", ")}
                  </span>
                </li>
              ))}
            </ul>
          </Section>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {Object.entries(data.counts).map(([name, n]) => (
              <div key={name} className="rounded-xl border bg-card p-3">
                <p className="text-2xl font-semibold">{n}</p>
                <p className="text-xs text-muted-foreground">{name.replaceAll("_", " ")}</p>
              </div>
            ))}
          </div>

          <Section title="Users">
            <Table
              head={["Email", "Role", "Created", "Last sign-in", "Docs", "Bookings", "Chats"]}
              empty="No users."
              rows={data.users.map((u) => [
                <span key="e" className={u.is_active ? "" : "line-through"}>{u.email}</span>,
                u.role,
                when(u.created_at),
                when(u.last_login_at),
                u.documents,
                u.bookings,
                u.conversations,
              ])}
            />
          </Section>

          <Section
            title="Document processing"
            description={Object.entries(data.documents_by_status)
              .map(([s, n]) => `${s}: ${n}`)
              .join(" · ") || "No documents yet."}
          >
            <Table
              head={["Owner", "Type", "Status", "Error", "Uploaded"]}
              empty="No failed documents."
              rows={data.failed_documents.map((d) => [
                d.owner, d.document_type ?? "–", d.status, d.error_code ?? "–", when(d.created_at),
              ])}
            />
          </Section>

          <Section title="Bookings" description="Most recent 100. References are masked.">
            <Table
              head={["Owner", "Type", "Provider", "Status", "Ref", "Amount", "Error", "Created"]}
              empty="No bookings yet."
              rows={data.bookings.map((b) => [
                b.owner, b.kind, b.provider, <BookingStatusBadge key="s" status={b.status} />,
                b.reference ?? "–", money(b.total_amount, b.currency), b.error_code ?? "–",
                when(b.created_at),
              ])}
            />
          </Section>

          <Section title="Assistant tools" description="Last 7 days.">
            <Table
              head={["Tool", "Calls", "Errors", "Avg latency"]}
              empty="No tool calls yet."
              rows={data.tools.map((t) => [t.tool, t.calls, t.errors, `${t.avg_latency_ms} ms`])}
            />
          </Section>

          <Section title="Recent errors">
            <div className="grid gap-6">
              <Table
                head={["Tool", "Error", "Latency", "When"]}
                empty="No tool errors."
                rows={data.tool_errors.map((e) => [
                  e.tool, e.error_code ?? "–", `${e.latency_ms} ms`, when(e.created_at),
                ])}
              />
              <Table
                head={["Failed job", "Attempts", "Last error", "When"]}
                empty="No failed jobs."
                rows={data.failed_jobs.map((j) => [j.kind, j.attempts, j.last_error ?? "–", when(j.updated_at)])}
              />
            </div>
          </Section>
        </div>
      )}
    </>
  );
}
