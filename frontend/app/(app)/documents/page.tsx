"use client";

import { useQuery } from "@tanstack/react-query";
import { FileText, Search } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useState } from "react";

import { StatusBadge } from "@/components/documents/document-status";
import { UploadDropzone } from "@/components/documents/upload-dropzone";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatSize, isInFlight, TYPE_LABELS } from "@/lib/documents";
import type { TravelDocument } from "@/types/api";

export default function DocumentsPage() {
  const [search, setSearch] = useState("");
  const query = useDeferredValue(search.trim());

  const { data: documents, isPending, error } = useQuery({
    queryKey: ["documents", query],
    queryFn: () =>
      api<TravelDocument[]>(`/documents${query ? `?q=${encodeURIComponent(query)}` : ""}`),
    // Keep polling while anything is still being processed.
    refetchInterval: (q) => (q.state.data?.some(isInFlight) ? 2000 : false),
  });

  return (
    <>
      <PageHeader
        title="Documents"
        description="Upload travel documents so the assistant can answer questions about your trips."
      />
      <div className="grid gap-6">
        <UploadDropzone />

        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            type="search"
            placeholder="Search by name or type"
            aria-label="Search documents"
            className="pl-8"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {error ? (
          <p className="text-sm text-destructive">{error.message}</p>
        ) : isPending ? (
          <div className="grid gap-2">
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-16 w-full" />)}
          </div>
        ) : documents.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center text-sm text-muted-foreground">
              {query ? "No documents match your search." : "No documents yet. Upload your first one above."}
            </CardContent>
          </Card>
        ) : (
          <ul className="grid gap-2">
            {documents.map((doc) => (
              <li key={doc.id}>
                <Link
                  href={`/documents/${doc.id}`}
                  className="flex items-center gap-3 rounded-xl border bg-card p-3 transition-colors hover:bg-muted/50"
                >
                  <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-muted">
                    <FileText className="size-5 text-muted-foreground" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{doc.filename}</span>
                    <span className="block truncate text-sm text-muted-foreground">
                      {doc.document_type ? TYPE_LABELS[doc.document_type] : "Not classified yet"}
                      {" · "}
                      {formatSize(doc.size_bytes)}
                      {" · "}
                      {new Date(doc.created_at).toLocaleDateString()}
                    </span>
                  </span>
                  <StatusBadge status={doc.status} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
