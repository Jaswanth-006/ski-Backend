"""Celery application with bulkheaded queues (01-BACKEND-PRD §9.1).

Three dedicated queues so load classes never share a worker pool:
  - core : latency-sensitive (exports, notifications) — the only one with tasks in v1
  - ml   : nightly forecast (Future Work) — declared, empty
  - ai   : STT + text-to-SQL (Future Work) — declared, empty

Run a worker (all queues) with:
    celery -A app.workers.celery_app worker -Q core,ml,ai --pool=solo   # solo on Windows
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery("ski", broker=settings.broker_url, backend=settings.result_backend)

celery_app.conf.update(
    task_default_queue="core",
    task_routes={
        "core.*": {"queue": "core"},
        "ml.*": {"queue": "ml"},
        "ai.*": {"queue": "ai"},
    },
    task_track_started=True,
    timezone="UTC",
    broker_connection_retry_on_startup=True,
)

# Register task modules.
celery_app.autodiscover_tasks(["app.workers"])

from app.workers import tasks as _tasks  # noqa: E402,F401  (import to register tasks)
