"""Celery tasks. Only the `core` queue has tasks in v1; `ml`/`ai` are provisioned but empty.

Tasks are sync (Celery), so async DB work runs via ``asyncio.run`` inside the task.
"""

from __future__ import annotations

import asyncio

from app.services import jobs as jobs_service
from app.workers.celery_app import celery_app


@celery_app.task(name="core.ping")  # type: ignore[untyped-decorator]  # celery decorator is untyped
def ping(job_id: str) -> str:
    """Trivial round-trip task: drives a jobs row from queued → done."""
    asyncio.run(jobs_service.run_ping(job_id))
    return job_id
