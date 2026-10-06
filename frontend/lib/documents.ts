import type { DocumentStatus, DocumentType, TravelDocument } from "@/types/api";

export const ACCEPTED_TYPES = ".pdf,.docx,.txt,.png,.jpg,.jpeg";
export const MAX_UPLOAD_MB = 15;

export const TYPE_LABELS: Record<DocumentType, string> = {
  passport: "Passport",
  visa: "Visa",
  flight_ticket: "Flight ticket",
  boarding_pass: "Boarding pass",
  hotel_booking: "Hotel booking",
  car_booking: "Car rental",
  insurance: "Travel insurance",
  itinerary: "Itinerary",
  identity_document: "ID document",
  other: "Other",
};

export const STATUS: Record<DocumentStatus, { label: string; tone: "muted" | "info" | "ok" | "bad" }> = {
  queued: { label: "Queued", tone: "muted" },
  processing: { label: "Processing", tone: "info" },
  extracted: { label: "Not indexed", tone: "muted" },
  ready: { label: "Ready for AI", tone: "ok" },
  failed: { label: "Failed", tone: "bad" },
  rejected: { label: "Rejected", tone: "bad" },
};

export function isInFlight(doc: Pick<TravelDocument, "status">) {
  return doc.status === "queued" || doc.status === "processing";
}

export function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function steps(doc: TravelDocument) {
  return [
    { label: "Uploaded", done: doc.steps.uploaded },
    { label: "Security scan", done: doc.steps.scanned },
    { label: doc.ocr_used ? "Text extracted (OCR)" : "Text extracted", done: doc.steps.text_extracted },
    { label: "Information extracted", done: doc.steps.fields_extracted },
    { label: "Ready for AI", done: doc.steps.indexed },
  ];
}
