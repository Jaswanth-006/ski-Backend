"""Jobs service: create job rows and drive their lifecycle (queued → running → done/failed).

Workers update the same `jobs` row the API created, so a client can poll status via
GET /v1/jobs/{id} (00-MAIN-PRD §10.3, 01-BACKEND-PRD §9.2).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job
from app.db.session import SessionLocal


async def create_job(db: AsyncSession, kind: str, requested_by: uuid.UUID | None = None) -> Job:
    job = Job(kind=kind, status="queued", requested_by=requested_by)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_job(db: AsyncSession, job_id: uuid.UUID) -> Job | None:
    return await db.get(Job, job_id)


async def run_ping(job_id: str) -> None:
    """Trivial `core` task body: mark running, do nothing, mark done.

    Opens its own session because it runs inside a Celery worker, not a request.
    Idempotent: a job already finished is left untouched (resumable-safe).
    """
    async with SessionLocal() as db:
        job = await db.get(Job, uuid.UUID(job_id))
        if job is None or job.status in ("done", "failed"):
            return
        job.status = "running"
        await db.commit()

        job.status = "done"
        job.result_url = None
        await db.commit()
