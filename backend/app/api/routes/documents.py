import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core import rate_limit
from app.core.config import get_settings
from app.db.database import get_db
from app.db.models import DocumentStatus, DocumentType, ExtractedEntity, User
from app.schemas.document import DocumentDetail, DocumentOut
from app.services import jobs
from app.services.document_service import DocumentService
from app.services.file_validation import DOCX

router = APIRouter(prefix="/documents", tags=["documents"])


def _service(request: Request, user: User, db: AsyncSession) -> DocumentService:
    return DocumentService(db, user, rate_limit.client_ip(request))


async def _detail(db: AsyncSession, service: DocumentService,
                  document_id: uuid.UUID) -> DocumentDetail:
    document = await service.get(document_id)
    entities = list((await db.execute(
        select(ExtractedEntity)
        .where(ExtractedEntity.document_id == document.id,
               ExtractedEntity.user_id == service.user.id)
        .order_by(ExtractedEntity.group_index, ExtractedEntity.id)
    )).scalars())
    return DocumentDetail.from_document_with_fields(document, entities)


async def _upload(request: Request, file: UploadFile, user: User, db: AsyncSession):
    settings = get_settings()
    rate_limit.enforce("upload", str(user.id), settings.UPLOAD_RATE_LIMIT_PER_HOUR, 3600)
    # Read at most one byte past the limit; the body-size middleware stops larger requests
    # before they are buffered.
    data = await file.read(settings.max_upload_bytes + 1)
    document = await _service(request, user, db).upload(data, file.filename)
    if settings.WORKER_MODE == "inline":
        jobs.kick_inline_worker()
    return DocumentOut.from_document(document)


@router.post("", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED,
             summary="Upload a travel document for processing")
async def upload_document(request: Request, file: UploadFile = File(...),
                          user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """Accepts PDF, DOCX, TXT, PNG and JPEG. The file is stored encrypted and processed in
    the background; poll `GET /api/documents/{id}` for its status."""
    return await _upload(request, file, user, db)


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED,
             summary="Upload a travel document (alias of POST /api/documents)")
async def upload_document_alias(request: Request, file: UploadFile = File(...),
                                user: User = Depends(get_current_user),
                                db: AsyncSession = Depends(get_db)):
    return await _upload(request, file, user, db)


@router.get("", response_model=list[DocumentOut], summary="List your documents")
async def list_documents(request: Request,
                         q: str | None = Query(None, max_length=100,
                                               description="Search filename or type"),
                         status_: DocumentStatus | None = Query(None, alias="status"),
                         document_type: DocumentType | None = None,
                         user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    documents = await _service(request, user, db).list(query=q, status=status_,
                                                       document_type=document_type)
    return [DocumentOut.from_document(d) for d in documents]


@router.get("/{document_id}", response_model=DocumentDetail,
            summary="A document with its extracted fields (identifiers masked)")
async def get_document(document_id: uuid.UUID, request: Request,
                       user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    return await _detail(db, _service(request, user, db), document_id)


@router.get("/{document_id}/file", summary="Download the original file",
            response_class=Response)
async def download_document(document_id: uuid.UUID, request: Request,
                            user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    document, data = await _service(request, user, db).read_file(document_id)
    disposition = "attachment" if document.content_type == DOCX else "inline"
    return Response(
        content=data,
        media_type=document.content_type,  # detected type, never the client's claim
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(document.filename)}",
            # The file is user content: never let it run scripts on our origin.
            "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self' data:; "
                                       "style-src 'unsafe-inline'",
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a document, its file, extracted data and index entries")
async def delete_document(document_id: uuid.UUID, request: Request,
                          user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    await _service(request, user, db).delete(document_id)


@router.post("/{document_id}/reprocess", response_model=DocumentOut,
             status_code=status.HTTP_202_ACCEPTED, summary="Retry a failed document")
async def reprocess_document(document_id: uuid.UUID, request: Request,
                             user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    document = await _service(request, user, db).reprocess(document_id)
    if get_settings().WORKER_MODE == "inline":
        jobs.kick_inline_worker()
    return DocumentOut.from_document(document)
