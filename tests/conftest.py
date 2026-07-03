"""Test fixtures.

The `client` fixture provides an httpx client wired to the FastAPI app with a
per-test async engine (NullPool → no cross-event-loop connection reuse) and two
seeded test users. It skips the test cleanly when no database is reachable, so the
DB-free unit tests still run in CI without Postgres.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from app.api.deps import get_db
from app.core.config import settings
from app.core.security import hash_password
from app.db.models import Job, RefreshToken, User
from app.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_ADMIN_PHONE = "7000000000"
TEST_OFFICE_PHONE = "7000000001"
TEST_DELIVERY_PHONE = "7000000002"
TEST_PASSWORD = "Test@123"


class SeededUsers:
    def __init__(self, admin_id: uuid.UUID, office_id: uuid.UUID, delivery_id: uuid.UUID) -> None:
        self.admin_id = admin_id
        self.office_id = office_id
        self.delivery_id = delivery_id


@pytest_asyncio.fixture
async def client() -> AsyncIterator[tuple[AsyncClient, SeededUsers]]:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    phones = [TEST_ADMIN_PHONE, TEST_OFFICE_PHONE, TEST_DELIVERY_PHONE]
    try:
        async with session_factory() as session:
            # Clean any leftovers from a previous run, then seed fresh test users.
            existing = (await session.scalars(select(User.id).where(User.phone.in_(phones)))).all()
            if existing:
                await session.execute(delete(Job).where(Job.requested_by.in_(existing)))
                await session.execute(
                    delete(RefreshToken).where(RefreshToken.user_id.in_(existing))
                )
                await session.execute(delete(User).where(User.id.in_(existing)))
            session.add_all(
                [
                    User(
                        name="Admin Test",
                        role="super_admin",
                        phone=TEST_ADMIN_PHONE,
                        password_hash=hash_password(TEST_PASSWORD),
                    ),
                    User(
                        name="Office Test",
                        role="office_admin",
                        phone=TEST_OFFICE_PHONE,
                        password_hash=hash_password(TEST_PASSWORD),
                    ),
                    User(
                        name="Delivery Test",
                        role="delivery",
                        phone=TEST_DELIVERY_PHONE,
                        password_hash=hash_password(TEST_PASSWORD),
                    ),
                ]
            )
            await session.commit()
            admin_id = await session.scalar(select(User.id).where(User.phone == TEST_ADMIN_PHONE))
            office_id = await session.scalar(select(User.id).where(User.phone == TEST_OFFICE_PHONE))
            delivery_id = await session.scalar(
                select(User.id).where(User.phone == TEST_DELIVERY_PHONE)
            )
    except (OSError, OperationalError, InterfaceError):
        await engine.dispose()
        import pytest

        pytest.skip("database not reachable — skipping integration tests")

    assert admin_id is not None and office_id is not None and delivery_id is not None
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client, SeededUsers(admin_id, office_id, delivery_id)

    # Teardown: drop dependency override and remove the test users + their tokens.
    app.dependency_overrides.pop(get_db, None)
    async with session_factory() as session:
        ids = [admin_id, office_id, delivery_id]
        await session.execute(delete(Job).where(Job.requested_by.in_(ids)))
        await session.execute(delete(RefreshToken).where(RefreshToken.user_id.in_(ids)))
        await session.execute(delete(User).where(User.id.in_(ids)))
        await session.commit()
    await engine.dispose()
