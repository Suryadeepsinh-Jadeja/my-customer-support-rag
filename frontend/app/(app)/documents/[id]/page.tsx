"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, Loader2, RotateCcw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";

import { ProcessingSteps, StatusBadge } from "@/components/documents/document-status";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import { formatSize, isInFlight, TYPE_LABELS } from "@/lib/documents";
import type { ExtractedField, TravelDocumentDetail } from "@/types/api";

function groupFields(fields: ExtractedField[]) {
  const groups = new Map<number, ExtractedField[]>();
  for (const f of fields) groups.set(f.group, [...(groups.get(f.group) ?? []), f]);
  return [...groups.entries()].sort(([a], [b]) => a - b);
}

function FieldList({ fields }: { fields: ExtractedField[] }) {
  return (
    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
      {fields.map((f) => (
        <div key={`${f.group}-${f.field}`} className="min-w-0">
          <dt className="text-xs text-muted-foreground">{f.label}</dt>
          <dd className="break-words font-medium">
            {f.value}
            {f.masked && <span className="sr-only"> (partly hidden)</span>}
          </dd>
          <dd className="text-xs text-muted-foreground">
            {f.page ? `Page ${f.page}` : "Page unknown"}
            {f.confidence != null && ` · ${Math.round(f.confidence * 100)}% confidence`}
            {f.method === "mrz" && " · verified from MRZ"}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export default function DocumentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();

  const remove = useMutation({
    mutationFn: () => api(`/documents/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ["document", id] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      toast.success("Document deleted, including its extracted information.");
      router.replace("/documents");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Couldn't delete the document."),
  });

  const { data: doc, error, isPending } = useQuery({
    queryKey: ["document", id],
    queryFn: () => api<TravelDocumentDetail>(`/documents/${id}`),
    // Stop fetching a document that has just been deleted.
    enabled: !remove.isSuccess,
    refetchInterval: (q) => (q.state.data && isInFlight(q.state.data) ? 2000 : false),
  });

  const retry = useMutation({
    mutationFn: () => api<TravelDocumentDetail>(`/documents/${id}/reprocess`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["document", id] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Couldn't retry."),
  });

  const back = (
    <Link href="/documents" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="size-4" aria-hidden /> Documents
    </Link>
  );

  if (isPending) {
    return <>{back}<Skeleton className="h-64 w-full" /></>;
  }
  if (error || !doc) {
    return (
      <>
        {back}
        <p className="text-muted-foreground">{error?.message ?? "We couldn't find that document."}</p>
      </>
    );
  }

  const groups = groupFields(doc.fields);
  const isTrip = doc.document_type === "flight_ticket" || doc.document_type === "itinerary";

  return (
    <>
      {back}
      <header className="mb-6 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-2xl font-semibold tracking-tight">{doc.filename}</h1>
          <p className="text-sm text-muted-foreground">
            {doc.document_type ? TYPE_LABELS[doc.document_type] : "Not classified yet"}
            {" · "}
            {formatSize(doc.size_bytes)}
            {doc.page_count ? ` · ${doc.page_count} page${doc.page_count > 1 ? "s" : ""}` : ""}
            {" · uploaded "}
            {new Date(doc.created_at).toLocaleString()}
          </p>
        </div>
        <StatusBadge status={doc.status} />
      </header>

      <div className="grid gap-6">
        {doc.error_message && (
          <Alert variant="destructive">
            <AlertTitle>{doc.status === "rejected" ? "File rejected" : "Processing failed"}</AlertTitle>
            <AlertDescription>{doc.error_message}</AlertDescription>
          </Alert>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Processing</CardTitle>
          </CardHeader>
          <CardContent>
            <ProcessingSteps doc={doc} />
          </CardContent>
        </Card>

        {doc.status === "extracted" && (
          <Card>
            <CardHeader>
              <CardTitle>Extracted information</CardTitle>
              <CardDescription>
                Read from your document
                {doc.analysis_method === "gemini" ? " by AI" : " automatically"}. Check anything
                important against the original. Identifiers are partly hidden.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-6">
              {doc.fields.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No details could be extracted from this document.
                </p>
              ) : (
                groups.map(([group, fields]) => (
                  <section key={group} className="grid gap-3">
                    {isTrip && groups.length > 1 && (
                      <h2 className="text-sm font-semibold">Flight {group + 1}</h2>
                    )}
                    <FieldList fields={fields} />
                  </section>
                ))
              )}
            </CardContent>
          </Card>
        )}

        <div className="flex flex-wrap gap-2">
          {doc.status !== "rejected" && (
            <a
              href={`/api/documents/${doc.id}/file`}
              target="_blank"
              rel="noopener noreferrer"
              className={buttonVariants({ variant: "outline" })}
            >
              <ExternalLink aria-hidden /> Open original
            </a>
          )}
          {doc.status === "failed" && (
            <Button variant="outline" onClick={() => retry.mutate()} disabled={retry.isPending}>
              {retry.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <RotateCcw aria-hidden />}
              Try again
            </Button>
          )}
          <AlertDialog>
            <AlertDialogTrigger render={<Button variant="destructive" />}>
              <Trash2 aria-hidden /> Delete
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete this document?</AlertDialogTitle>
                <AlertDialogDescription>
                  The file and everything extracted from it will be permanently removed. The
                  assistant will no longer be able to use it.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <Button variant="destructive" onClick={() => remove.mutate()} disabled={remove.isPending}>
                  {remove.isPending && <Loader2 className="animate-spin" aria-hidden />}
                  Delete permanently
                </Button>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>
    </>
  );
}
