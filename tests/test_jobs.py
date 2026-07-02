"""Tests for the jobs API and the core task body (require a database).

The real Redis→worker round-trip is verified live; here we stub the broker (ping.delay)
and exercise the DB-facing pieces: enqueue creates a queued row, owner scoping, and the
task body driving a job to `done`.
"""

from __future__ import annotations

import app.services.jobs as jobs_module
import pytest
from app.core.config import settings
from app.db.models import Job
from app.services import jobs as jobs_service
from app.workers.tasks import ping
from httpx import AsyncClient
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_DELIVERY_PHONE, TEST_OFFICE_PHONE, TEST_PASSWORD, SeededUsers


async def _login(client: AsyncClient, phone: str) -> str:
    res = await client.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    assert res.status_code == 200, res.text
    token: str = res.json()["access_token"]
    return token


async def test_enqueue_ping_creates_queued_job(
    client: tuple[AsyncClient, SeededUsers], monkeypatch: pytest.MonkeyPatch
) -> None:
    http, _ = client
    monkeypatch.setattr(ping, "delay", lambda *a, **k: None)  # stub the broker
    token = await _login(http, TEST_OFFICE_PHONE)
    headers = {"Authorization": f"Bearer {token}"}

    res = await http.post("/v1/jobs/ping", headers=headers)
    assert res.status_code == 202
    job_id = res.json()["job_id"]
    assert res.json()["status"] == "queued"

    got = await http.get(f"/v1/jobs/{job_id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["kind"] == "ping"


async def test_job_owner_scoping(
    client: tuple[AsyncClient, SeededUsers], monkeypatch: pytest.MonkeyPatch
) -> None:
    http, _ = client
    monkeypatch.setattr(ping, "delay", lambda *a, **k: None)
    office_token = await _login(http, TEST_OFFICE_PHONE)
    delivery_token = await _login(http, TEST_DELIVERY_PHONE)

    created = await http.post("/v1/jobs/ping", headers={"Authorization": f"Bearer {office_token}"})
    job_id = created.json()["job_id"]

    # A delivery user cannot poll someone else's job.
    denied = await http.get(
        f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {delivery_token}"}
    )
    assert denied.status_code == 403


async def test_run_ping_marks_job_done(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    # run_ping opens its own session; point it at this in-loop engine.
    monkeypatch.setattr(jobs_module, "SessionLocal", session_factory)
    try:
        async with session_factory() as db:
            job = await jobs_service.create_job(db, kind="ping")
            job_id = job.id
            assert job.status == "queued"

        await jobs_service.run_ping(str(job_id))

        async with session_factory() as db:
            done = await db.get(Job, job_id)
            assert done is not None
            assert done.status == "done"
            await db.delete(done)
            await db.commit()
    except (OSError, OperationalError, InterfaceError):
        pytest.skip("database not reachable")
    finally:
        await engine.dispose()
