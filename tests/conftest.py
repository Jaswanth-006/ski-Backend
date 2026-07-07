"""Test fixtures.

The `client` fixture provides an httpx client wired to the FastAPI app with a
per-test async engine (NullPool → no cross-event-loop connection reuse) and three
seeded test users. It skips the test cleanly when no database is reachable, so the
DB-free unit tests still run in CI without Postgres.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence

import pytest_asyncio
from app.api.deps import get_db
from app.core.config import settings
from app.core.security import hash_password
from app.db.models import (
    AuditLog,
    CashDenomination,
    CashLedger,
    DaySheetStatus,
    Expense,
    ExpenseItem,
    Job,
    Price,
    RefreshToken,
    Sale,
    SaleLine,
    StockLedger,
    User,
)
from app.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, or_, select
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


async def _purge_users(session: AsyncSession, ids: Sequence[uuid.UUID]) -> None:
    """Delete the test users and every row that references them, in FK-safe order."""
    if not ids:
        return
    sale_ids = (
        await session.scalars(
            select(Sale.id).where(or_(Sale.delivery_id.in_(ids), Sale.approved_by.in_(ids)))
        )
    ).all()
    if sale_ids:
        await session.execute(
            delete(CashDenomination).where(CashDenomination.sale_id.in_(sale_ids))
        )
        await session.execute(delete(CashLedger).where(CashLedger.sale_id.in_(sale_ids)))
        await session.execute(delete(SaleLine).where(SaleLine.sale_id.in_(sale_ids)))
        await session.execute(delete(StockLedger).where(StockLedger.ref_id.in_(sale_ids)))
        await session.execute(delete(Sale).where(Sale.id.in_(sale_ids)))
    await session.execute(delete(StockLedger).where(StockLedger.created_by.in_(ids)))
    await session.execute(delete(Price).where(Price.created_by.in_(ids)))
    await session.execute(delete(Expense).where(Expense.created_by.in_(ids)))
    await session.execute(delete(ExpenseItem).where(ExpenseItem.created_by.in_(ids)))
    await session.execute(delete(DaySheetStatus).where(DaySheetStatus.closed_by.in_(ids)))
    await session.execute(delete(AuditLog).where(AuditLog.actor_id.in_(ids)))
    await session.execute(delete(Job).where(Job.requested_by.in_(ids)))
    await session.execute(delete(RefreshToken).where(RefreshToken.user_id.in_(ids)))
    await session.execute(delete(User).where(User.id.in_(ids)))


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
            existing = (await session.scalars(select(User.id).where(User.phone.in_(phones)))).all()
            await _purge_users(session, existing)
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

    app.dependency_overrides.pop(get_db, None)
    async with session_factory() as session:
        await _purge_users(session, [admin_id, office_id, delivery_id])
        await session.commit()
    await engine.dispose()
