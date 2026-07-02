"""Job routes: enqueue a demo `core` task and poll job status (00-MAIN-PRD §10.3).

`POST /v1/jobs/ping` is the Phase 0-F round-trip demonstrator (Redis → worker → jobs row).
Real producers (Excel export, etc.) arrive in Phase 4.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_roles
from app.db.models import Job, User
from app.schemas.jobs import JobEnqueued, JobOut
from app.services import jobs as jobs_service
from app.workers.tasks import ping

router = APIRouter(tags=["jobs"])


@router.post("/jobs/ping", response_model=JobEnqueued, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_ping(
    current_user: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> JobEnqueued:
    job = await jobs_service.create_job(db, kind="ping", requested_by=current_user.id)
    ping.delay(str(job.id))  # hand off to the core worker via Redis
    return JobEnqueued(job_id=job.id, status=job.status)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Job:
    job = await jobs_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="job not found")
    # Owner-scoped: only the requester (or an admin/office user) may poll a job.
    is_admin = current_user.role in ("super_admin", "office_admin")
    if not is_admin and job.requested_by != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="cannot access another user's job")
    return job
