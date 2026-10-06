"""User-facing document operations. Every query is scoped to the authenticated user.

A document that belongs to someone else is reported as "not found", never "forbidden",
so its existence isn't revealed either.
"""

import hashlib
import logging
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ServiceUnavailableError
from app.db.models import Document, DocumentStatus, DocumentType, User
from app.services import audit_service, jobs
from app.services.document_processor import JOB_KIND
from app.services.file_validation import validate_upload
from app.services.storage import ObjectNotFoundError, StorageError, get_storage

logger = logging.getLogger("travel.documents")


class DocumentService:
    def __init__(self, session: AsyncSession, user: User, ip: str | None = None):
        self.session = session
        self.user = user
        self.ip = ip
        self.settings = get_settings()
        self.storage = get_storage()

    async def _audit(self, action: str, document: Document, **details) -> None:
        await audit_service.record(
            self.session, action, user_id=self.user.id, ip_address=self.ip,
            resource_type="document", resource_id=str(document.id), details=details,
        )

    async def upload(self, data: bytes, filename: str | None) -> Document:
        checked = validate_upload(data, filename, self.settings.max_upload_bytes)

        count = (await self.session.execute(
            select(func.count()).select_from(Document).where(Document.user_id == self.user.id)
        )).scalar_one()
        if count >= self.settings.MAX_DOCUMENTS_PER_USER:
            raise ConflictError("You've reached the document limit. Delete some documents first.")

        sha256 = hashlib.sha256(data).hexdigest()
        duplicate = (await self.session.execute(
            select(Document.id).where(Document.user_id == self.user.id, Document.sha256 == sha256)
        )).scalar_one_or_none()
        if duplicate:
            raise ConflictError("You've already uploaded this file.")

        document_id = uuid.uuid4()
        # No filename or other PII in the object key.
        key = f"users/{self.user.id}/documents/{document_id}"
        try:
            await self.storage.put(key, data, checked.content_type)
        except StorageError as exc:
            logger.error("document upload: storage failed", extra={"error": str(exc)})
            raise ServiceUnavailableError("We couldn't store your file. Please try again.") from exc

        document = Document(
            id=document_id, user_id=self.user.id, filename=checked.filename,
            content_type=checked.content_type, size_bytes=len(data), sha256=sha256,
            storage_key=key, status=DocumentStatus.QUEUED,
        )
        self.session.add(document)
        jobs.enqueue(self.session, JOB_KIND, document_id)
        await self._audit("document.upload", document, content_type=checked.content_type,
                          size_bytes=len(data))
        try:
            await self.session.commit()
        except IntegrityError as exc:  # concurrent duplicate upload
            await self.session.rollback()
            await self._delete_object(key)
            raise ConflictError("You've already uploaded this file.") from exc
        except Exception:
            await self.session.rollback()
            await self._delete_object(key)  # don't leave an orphaned file behind
            raise
        return document

    async def list(self, *, query: str | None = None, status: DocumentStatus | None = None,
                   document_type: DocumentType | None = None) -> list[Document]:
        stmt = select(Document).where(Document.user_id == self.user.id)
        if status:
            stmt = stmt.where(Document.status == status)
        if document_type:
            stmt = stmt.where(Document.document_type == document_type)
        if query:
            like = f"%{query.strip().lower()}%"
            stmt = stmt.where(or_(func.lower(Document.filename).like(like),
                                  func.lower(Document.document_type).like(like)))
        stmt = stmt.order_by(Document.created_at.desc())
        return list((await self.session.execute(stmt)).scalars())

    async def get(self, document_id: uuid.UUID) -> Document:
        document = (await self.session.execute(
            select(Document).where(Document.id == document_id, Document.user_id == self.user.id)
        )).scalar_one_or_none()
        if document is None:
            raise NotFoundError("We couldn't find that document.")
        return document

    async def read_file(self, document_id: uuid.UUID) -> tuple[Document, bytes]:
        document = await self.get(document_id)
        if document.status == DocumentStatus.REJECTED:
            raise NotFoundError("This file was removed because it failed the security scan.")
        try:
            data = await self.storage.get(document.storage_key)
        except ObjectNotFoundError as exc:
            raise NotFoundError("The file is no longer available.") from exc
        except StorageError as exc:
            raise ServiceUnavailableError() from exc
        await self._audit("document.download", document)
        await self.session.commit()
        return document, data

    async def delete(self, document_id: uuid.UUID) -> None:
        """Remove the stored file, the record, its pages, fields and jobs (FK cascade)."""
        document = await self.get(document_id)
        # File first: if storage is down nothing changes and the user can retry. The
        # reverse order could leave an encrypted file nobody can reach or delete.
        try:
            await self.storage.delete(document.storage_key)
        except StorageError as exc:
            raise ServiceUnavailableError("We couldn't delete the file. Please try again.") from exc
        await self._audit("document.delete", document,
                          document_type=document.document_type, size_bytes=document.size_bytes)
        await self.session.delete(document)
        await self.session.commit()

    async def reprocess(self, document_id: uuid.UUID) -> Document:
        document = await self.get(document_id)
        if document.status != DocumentStatus.FAILED:
            raise ConflictError("Only documents that failed processing can be retried.")
        document.status = DocumentStatus.QUEUED
        document.error_code = None
        jobs.enqueue(self.session, JOB_KIND, document.id)
        await self._audit("document.reprocess", document)
        await self.session.commit()
        return document

    async def _delete_object(self, key: str) -> None:
        try:
            await self.storage.delete(key)
        except StorageError:
            logger.error("could not remove stored file after a failed upload",
                         extra={"key": key})
