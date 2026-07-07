"""Celery tasks. Only the `core` queue has tasks in v1; `ml`/`ai` are provisioned but empty.

Tasks are sync (Celery), so async DB work runs via ``asyncio.run`` inside the task.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid

from app.core import storage
from app.db.models import Job
from app.db.session import SessionLocal
from app.services import day_sheet as day_sheet_service
from app.services import jobs as jobs_service
from app.workers.celery_app import celery_app
from app.workers.exports import build_day_sheet_xlsx

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@celery_app.task(name="core.ping")  # type: ignore[untyped-decorator]  # celery decorator is untyped
def ping(job_id: str) -> str:
    """Trivial round-trip task: drives a jobs row from queued → done."""
    asyncio.run(jobs_service.run_ping(job_id))
    return job_id


@celery_app.task(name="core.export_day_sheet")  # type: ignore[untyped-decorator]
def export_day_sheet(job_id: str, date_str: str) -> str:
    """Build the day sheet .xlsx, upload it, and set the job's result URL."""
    asyncio.run(_run_export(job_id, date_str))
    return job_id


async def _run_export(job_id: str, date_str: str) -> None:
    async with SessionLocal() as db:
        job = await db.get(Job, uuid.UUID(job_id))
        if job is None:
            return
        job.status = "running"
        await db.commit()
        try:
            sheet = await day_sheet_service.get_day_sheet(db, dt.date.fromisoformat(date_str))
            data = build_day_sheet_xlsx(sheet)
            key = f"day-sheets/{date_str}-{job_id}.xlsx"
            storage.ensure_bucket()
            storage.put_bytes(key, data, _XLSX_MIME)
            job.result_url = storage.presigned_get_url(key)
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 — record failure on the job, don't crash the worker
            job.status = "failed"
            job.error = str(exc)
        await db.commit()
