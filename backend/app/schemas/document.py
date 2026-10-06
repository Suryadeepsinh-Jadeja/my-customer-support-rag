import uuid

from pydantic import BaseModel, ConfigDict, computed_field

from app.core.logging import mask
from app.db.models import Document, DocumentStatus, DocumentType, ExtractedEntity
from app.schemas.common import UtcDatetime

# Identifiers shown only masked in the UI and API listings.
MASKED_FIELDS = {
    "passport_number", "visa_number", "document_number", "policy_number", "ticket_number",
}

ERROR_MESSAGES = {
    "invalid_pdf": "This PDF appears to be damaged and couldn't be read.",
    "encrypted_pdf": "This PDF is password-protected. Upload a copy without a password.",
    "too_many_pages": "This PDF has too many pages.",
    "invalid_docx": "This Word document appears to be damaged and couldn't be read.",
    "ocr_unavailable": "This file is a scan or photo and text recognition isn't available "
                       "right now.",
    "ocr_failed": "We couldn't read the text in this scan or photo.",
    "no_text_found": "We couldn't find any text in this file.",
    "malware_detected": "This file failed our security scan and was removed.",
    "scanner_unavailable": "The security scan is temporarily unavailable.",
    "storage_unavailable": "The file store is temporarily unavailable.",
    "file_missing": "The stored file is missing. Please upload it again.",
    "internal_error": "Something went wrong while processing this file.",
}

LABELS = {
    "pnr": "PNR / booking reference",
    "date_of_birth": "Date of birth",
    "check_in": "Check-in",
    "check_out": "Check-out",
    "pickup_datetime": "Pick-up",
    "dropoff_datetime": "Drop-off",
    "pickup_location": "Pick-up location",
    "dropoff_location": "Drop-off location",
}


def field_label(name: str) -> str:
    return LABELS.get(name, name.replace("_", " ").capitalize())


def masked_value(field: str, value: str) -> tuple[str, bool]:
    if field in MASKED_FIELDS:
        return mask(value) or "", True
    if field == "date_of_birth" and len(value) == 10:
        return f"{value[:4]}-**-**", True
    return value, False


class DocumentSteps(BaseModel):
    uploaded: bool
    scanned: bool
    text_extracted: bool
    fields_extracted: bool


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    error_code: str | None
    document_type: DocumentType | None
    type_confidence: float | None
    analysis_method: str | None
    page_count: int | None
    ocr_used: bool
    created_at: UtcDatetime
    steps: DocumentSteps

    @computed_field  # type: ignore[prop-decorator]
    @property
    def error_message(self) -> str | None:
        if not self.error_code:
            return None
        return ERROR_MESSAGES.get(self.error_code, ERROR_MESSAGES["internal_error"])

    @classmethod
    def from_document(cls, doc: Document) -> "DocumentOut":
        return cls.model_validate({**_base(doc)})


class ExtractedFieldOut(BaseModel):
    field: str
    label: str
    value: str
    masked: bool
    group: int
    page: int | None
    confidence: float | None
    method: str


class DocumentDetail(DocumentOut):
    fields: list[ExtractedFieldOut]

    @classmethod
    def from_document_with_fields(cls, doc: Document,
                                  entities: list[ExtractedEntity]) -> "DocumentDetail":
        fields = []
        for e in entities:
            value, masked = masked_value(e.field, e.value)
            fields.append(ExtractedFieldOut(
                field=e.field, label=field_label(e.field), value=value, masked=masked,
                group=e.group_index, page=e.page, confidence=e.confidence, method=e.method,
            ))
        return cls.model_validate({**_base(doc), "fields": fields})


def _base(doc: Document) -> dict:
    return {
        "id": doc.id, "filename": doc.filename, "content_type": doc.content_type,
        "size_bytes": doc.size_bytes, "status": doc.status, "error_code": doc.error_code,
        "document_type": doc.document_type, "type_confidence": doc.type_confidence,
        "analysis_method": doc.analysis_method, "page_count": doc.page_count,
        "ocr_used": doc.ocr_used, "created_at": doc.created_at,
        "steps": DocumentSteps(
            uploaded=True, scanned=doc.scanned_at is not None,
            text_extracted=doc.text_extracted_at is not None,
            fields_extracted=doc.fields_extracted_at is not None,
        ),
    }
