"""The background pipeline for one uploaded document.

    load (decrypt) -> malware scan -> text extraction / OCR -> classification +
    structured extraction -> store pages and fields -> status "extracted"

Chunking and embeddings follow in phase 3.
"""

import logging

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import (
    Document,
    DocumentPage,
    DocumentStatus,
    DocumentType,
    ExtractedEntity,
    ProcessingJob,
)
from app.services import audit_service, jobs
from app.services.extraction_service import GeminiAnalyzer, RuleAnalyzer, analyze_document
from app.services.llm_service import get_llm
from app.services.malware import ScannerUnavailableError, get_scanner
from app.services.ocr import get_ocr
from app.services.storage import ObjectNotFoundError, StorageError, get_storage
from app.services.text_extraction import ExtractionError, extract_pages

logger = logging.getLogger("travel.documents")

JOB_KIND = "process_document"
# Extraction errors worth retrying (an external OCR service may recover).
_RETRYABLE_EXTRACTION = {"ocr_failed"}


def _primary_analyzer():
    settings = get_settings()
    provider = settings.DOCUMENT_AI_PROVIDER
    if provider == "rules" or (provider == "auto" and not settings.GEMINI_API_KEY):
        return None
    return GeminiAnalyzer(get_llm())


async def process_document(session: AsyncSession, job: ProcessingJob) -> None:
    document = await session.get(Document, job.document_id) if job.document_id else None
    if document is None:
        return  # deleted before we got to it
    settings = get_settings()

    document.status = DocumentStatus.PROCESSING
    document.error_code = None
    await session.commit()

    storage = get_storage()
    try:
        data = await storage.get(document.storage_key)
    except ObjectNotFoundError as exc:
        raise jobs.JobError("file_missing", retryable=False) from exc
    except StorageError as exc:
        raise jobs.JobError("storage_unavailable", retryable=True) from exc

    try:
        scan = await get_scanner().scan(data)
    except ScannerUnavailableError as exc:
        raise jobs.JobError("scanner_unavailable", retryable=True) from exc
    if not scan.clean:
        # Never keep or parse an infected file.
        await storage.delete(document.storage_key)
        document.status = DocumentStatus.REJECTED
        document.error_code = "malware_detected"
        await audit_service.record(
            session, "document.rejected", user_id=document.user_id, actor="system",
            status="failure", resource_type="document", resource_id=str(document.id),
            details={"signature": scan.signature},
        )
        return
    document.scanned_at = jobs.now()
    await session.commit()  # keep the passed scan even if a later step fails

    try:
        pages = await extract_pages(data, document.content_type, get_ocr(),
                                    settings.MAX_PDF_PAGES)
    except ExtractionError as exc:
        raise jobs.JobError(exc.code, retryable=exc.code in _RETRYABLE_EXTRACTION) from exc

    # Reprocessing replaces earlier results.
    await session.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
    await session.execute(
        delete(ExtractedEntity).where(ExtractedEntity.document_id == document.id)
    )
    session.add_all(
        DocumentPage(document_id=document.id, page_number=p.page_number, text=p.text, ocr=p.ocr)
        for p in pages
    )
    document.page_count = len(pages)
    document.ocr_used = any(p.ocr for p in pages)
    document.text_extracted_at = jobs.now()

    analysis, method = await analyze_document(pages, _primary_analyzer(), RuleAnalyzer())
    extracted_at = jobs.now()
    session.add_all(
        ExtractedEntity(
            document_id=document.id, user_id=document.user_id,
            entity_type=analysis.document_type.value, field=f.field, value=f.value,
            group_index=f.group, page=f.page, confidence=f.confidence,
            # The rules analyzer gives check-digit-verified MRZ values 0.98, labels 0.6.
            method="mrz" if method == "rules" and f.confidence >= 0.95 else method,
            extracted_at=extracted_at,
        )
        for f in analysis.fields
    )
    document.document_type = DocumentType(analysis.document_type)
    document.type_confidence = analysis.type_confidence
    document.analysis_method = method
    document.fields_extracted_at = extracted_at
    document.status = DocumentStatus.EXTRACTED

    await audit_service.record(
        session, "document.processed", user_id=document.user_id, actor="system",
        resource_type="document", resource_id=str(document.id),
        details={"document_type": analysis.document_type.value, "pages": len(pages),
                 "fields": len(analysis.fields), "method": method, "ocr": document.ocr_used},
    )
    logger.info("document.processed", extra={
        "document": str(document.id), "document_type": analysis.document_type.value,
        "pages": len(pages), "fields": len(analysis.fields), "method": method,
    })


async def on_final_failure(session: AsyncSession, job: ProcessingJob, code: str) -> None:
    document = await session.get(Document, job.document_id) if job.document_id else None
    if document is None:
        return
    document.status = DocumentStatus.FAILED
    document.error_code = code
    await audit_service.record(
        session, "document.processed", user_id=document.user_id, actor="system",
        status="failure", resource_type="document", resource_id=str(document.id),
        details={"error": code},
    )


async def on_retry(session: AsyncSession, job: ProcessingJob, code: str) -> None:
    """Show the document as queued again while its job waits to be retried."""
    document = await session.get(Document, job.document_id) if job.document_id else None
    if document is not None:
        document.status = DocumentStatus.QUEUED


jobs.register(JOB_KIND, process_document, on_retry=on_retry, on_final_failure=on_final_failure)
