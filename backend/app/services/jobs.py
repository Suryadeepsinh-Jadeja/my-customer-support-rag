"""A small database-backed job queue.

Jobs are claimed atomically (`UPDATE ... WHERE status='queued'`, with SKIP LOCKED on
PostgreSQL), so any number of workers can run side by side. Failed jobs are retried with
exponential backoff; jobs whose worker died are re-queued after JOB_LOCK_TIMEOUT.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_sessionmaker
from app.db.models import JobStatus, ProcessingJob

logger = logging.getLogger("travel.jobs")

JOB_LOCK_TIMEOUT = timedelta(minutes=15)
RETRY_BASE_SECONDS = 30


class JobError(Exception):
    """A handler failure. `code` is safe to store and show; never document content."""

    def __init__(self, code: str, *, retryable: bool):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


Handler = Callable[[AsyncSession, ProcessingJob], Awaitable[None]]
Hook = Callable[[AsyncSession, ProcessingJob, str], Awaitable[None]]


@dataclass(frozen=True)
class _Registration:
    handler: Handler
    on_retry: Hook | None = None
    on_final_failure: Hook | None = None


_handlers: dict[str, _Registration] = {}


def register(kind: str, handler: Handler, *, on_retry: Hook | None = None,
             on_final_failure: Hook | None = None) -> None:
    _handlers[kind] = _Registration(handler, on_retry, on_final_failure)


def now() -> datetime:
    return datetime.now(UTC)


def enqueue(session: AsyncSession, kind: str, document_id: uuid.UUID | None = None,
            delay: timedelta | None = None) -> ProcessingJob:
    """Add a job to the caller's transaction."""
    job = ProcessingJob(kind=kind, document_id=document_id, status=JobStatus.QUEUED,
                        run_after=now() + (delay or timedelta()))
    session.add(job)
    return job


async def claim_next(session: AsyncSession) -> uuid.UUID | None:
    # Recover jobs from workers that died mid-run.
    await session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.status == JobStatus.RUNNING,
               ProcessingJob.locked_at < now() - JOB_LOCK_TIMEOUT)
        .values(status=JobStatus.QUEUED, locked_at=None)
    )
    candidate = (
        select(ProcessingJob.id)
        .where(ProcessingJob.status == JobStatus.QUEUED, ProcessingJob.run_after <= now())
        .order_by(ProcessingJob.run_after)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    claimed = (await session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == candidate, ProcessingJob.status == JobStatus.QUEUED)
        .values(status=JobStatus.RUNNING, locked_at=now(),
                attempts=ProcessingJob.attempts + 1)
        .returning(ProcessingJob.id)
    )).scalar_one_or_none()
    await session.commit()
    return claimed


async def run_job(job_id: uuid.UUID) -> None:
    async with get_sessionmaker()() as session:
        job = await session.get(ProcessingJob, job_id)
        if job is None:
            return
        registration = _handlers.get(job.kind)
        try:
            if registration is None:
                raise JobError("unknown_job_kind", retryable=False)
            await registration.handler(session, job)
            job.status = JobStatus.SUCCEEDED
            job.last_error = None
            await session.commit()
            logger.info("job.succeeded", extra={"kind": job.kind, "job": str(job.id)})
        except Exception as exc:
            await session.rollback()
            error = exc if isinstance(exc, JobError) else JobError("internal_error",
                                                                   retryable=True)
            if not isinstance(exc, JobError):
                logger.exception("job.crashed", extra={"kind": job.kind, "job": str(job.id)})
            job = await session.get(ProcessingJob, job_id, populate_existing=True)
            if job is None:  # e.g. the document was deleted meanwhile
                return
            job.last_error = error.code
            if error.retryable and job.attempts < job.max_attempts:
                job.status = JobStatus.QUEUED
                job.run_after = now() + timedelta(seconds=RETRY_BASE_SECONDS * 2 ** job.attempts)
                job.locked_at = None
                logger.warning("job.retry", extra={"kind": job.kind, "code": error.code,
                                                   "attempt": job.attempts})
                if registration and registration.on_retry:
                    await registration.on_retry(session, job, error.code)
            else:
                job.status = JobStatus.FAILED
                logger.warning("job.failed", extra={"kind": job.kind, "code": error.code})
                if registration and registration.on_final_failure:
                    await registration.on_final_failure(session, job, error.code)
            await session.commit()


async def run_pending(max_jobs: int = 100) -> int:
    """Run queued jobs until none are due (or max_jobs). Returns how many ran."""
    ran = 0
    while ran < max_jobs:
        async with get_sessionmaker()() as session:
            job_id = await claim_next(session)
        if job_id is None:
            break
        await run_job(job_id)
        ran += 1
    return ran


# ------------------------------------------------------------- inline mode

_inline_tasks: set[asyncio.Task] = set()
_inline_lock = asyncio.Lock()


def kick_inline_worker() -> None:
    """Development mode: process queued jobs in this process, in the background."""

    async def drain() -> None:
        async with _inline_lock:
            await run_pending()

    task = asyncio.get_running_loop().create_task(drain())
    _inline_tasks.add(task)
    task.add_done_callback(_inline_tasks.discard)
