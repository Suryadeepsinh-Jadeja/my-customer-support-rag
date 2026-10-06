from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.routes.health import readiness
from app.core.logging import mask, mask_email
from app.db.base import utcnow
from app.db.database import get_db
from app.db.models import (
    Booking,
    Conversation,
    Document,
    DocumentStatus,
    JobStatus,
    ProcessingJob,
    ToolExecution,
    User,
)
from app.schemas.admin import (
    AdminBooking,
    AdminDocument,
    AdminJobError,
    AdminOverview,
    AdminToolError,
    AdminToolStat,
    AdminUser,
)
from app.services import audit_service

router = APIRouter(prefix="/admin", tags=["admin"])

TOOL_WINDOW = timedelta(days=7)


async def _count(db: AsyncSession, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _per_user(db: AsyncSession, column) -> dict:
    rows = await db.execute(select(column, func.count()).group_by(column))
    return dict(rows.all())


@router.get("/overview", response_model=AdminOverview,
            summary="System health, users, processing, bookings, tool usage and errors")
async def overview(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    docs_per_user = await _per_user(db, Document.user_id)
    bookings_per_user = await _per_user(db, Booking.user_id)
    conversations_per_user = await _per_user(db, Conversation.user_id)
    users = list((await db.execute(
        select(User).order_by(User.created_at.desc()).limit(200))).scalars())
    emails = {u.id: mask_email(u.email) or "" for u in users}

    async def owner(user_id) -> str:
        if user_id not in emails:
            email = (await db.execute(select(User.email).where(User.id == user_id))).scalar()
            emails[user_id] = mask_email(email) or ""
        return emails[user_id]

    by_status = dict((await db.execute(
        select(Document.status, func.count()).group_by(Document.status))).all())
    failed_docs = (await db.execute(
        select(Document).where(Document.status.in_([DocumentStatus.FAILED,
                                                    DocumentStatus.REJECTED]))
        .order_by(Document.created_at.desc()).limit(50))).scalars()

    bookings = (await db.execute(
        select(Booking).order_by(Booking.created_at.desc()).limit(100))).scalars()

    since = utcnow() - TOOL_WINDOW
    tool_rows = (await db.execute(
        select(ToolExecution.tool, func.count(),
               func.sum(case((ToolExecution.status == "error", 1), else_=0)),
               func.avg(ToolExecution.latency_ms))
        .where(ToolExecution.created_at >= since)
        .group_by(ToolExecution.tool).order_by(func.count().desc()))).all()
    tool_errors = (await db.execute(
        select(ToolExecution).where(ToolExecution.status == "error")
        .order_by(ToolExecution.created_at.desc()).limit(30))).scalars()
    failed_jobs = (await db.execute(
        select(ProcessingJob).where(ProcessingJob.status == JobStatus.FAILED)
        .order_by(ProcessingJob.updated_at.desc()).limit(30))).scalars()

    result = AdminOverview(
        ready=await readiness(),
        counts={
            "users": await _count(db, User),
            "documents": await _count(db, Document),
            "conversations": await _count(db, Conversation),
            "bookings": await _count(db, Booking),
            "tool_calls_7d": sum(r[1] for r in tool_rows),
        },
        users=[AdminUser(
            id=u.id, email=u.email, role=u.role.value, is_active=u.is_active,
            created_at=u.created_at, last_login_at=u.last_login_at,
            documents=docs_per_user.get(u.id, 0), bookings=bookings_per_user.get(u.id, 0),
            conversations=conversations_per_user.get(u.id, 0)) for u in users],
        documents_by_status={s.value: n for s, n in by_status.items()},
        failed_documents=[AdminDocument(
            id=d.id, owner=await owner(d.user_id),
            document_type=d.document_type.value if d.document_type else None,
            status=d.status.value, error_code=d.error_code, created_at=d.created_at)
            for d in failed_docs],
        bookings=[AdminBooking(
            id=b.id, owner=await owner(b.user_id), kind=b.kind.value, provider=b.provider,
            status=b.status.value, reference=mask(b.provider_ref, 2),
            total_amount=b.total_amount, currency=b.currency, error_code=b.error_code,
            created_at=b.created_at) for b in bookings],
        tools=[AdminToolStat(tool=t, calls=n, errors=int(e or 0), avg_latency_ms=round(a or 0))
               for t, n, e, a in tool_rows],
        tool_errors=[AdminToolError(tool=t.tool, error_code=t.error_code,
                                    latency_ms=t.latency_ms, created_at=t.created_at)
                     for t in tool_errors],
        failed_jobs=[AdminJobError(id=j.id, kind=j.kind, attempts=j.attempts,
                                   last_error=j.last_error, updated_at=j.updated_at)
                     for j in failed_jobs],
    )
    await audit_service.record(db, "admin.overview_view", user_id=admin.id, actor="admin")
    await db.commit()
    return result
