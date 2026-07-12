"""Daily expenses tests (Phase 4-C)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.core.config import settings
from app.db.models import CashLedger, Expense, ExpenseItem
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_ADMIN_PHONE, TEST_PASSWORD, SeededUsers

ITEM_NAME = "ZZ-exp-fuel"
AMOUNT = 237  # distinctive amount so the cash-ledger check is unambiguous
DAY_DATE = dt.date(2098, 6, 2)  # isolated from other suites
DAY = DAY_DATE.isoformat()


async def _token(http: AsyncClient, phone: str) -> str:
    res = await http.post("/v1/auth/login", json={"phone": phone, "password": TEST_PASSWORD})
    token: str = res.json()["access_token"]
    return token


async def _cleanup() -> None:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        await db.execute(
            delete(CashLedger).where(
                CashLedger.kind == "expense", CashLedger.amount == Decimal(-AMOUNT)
            )
        )
        item_ids = (
            await db.scalars(select(ExpenseItem.id).where(ExpenseItem.name == ITEM_NAME))
        ).all()
        for iid in item_ids:
            await db.execute(delete(Expense).where(Expense.item_id == iid))
        await db.execute(delete(ExpenseItem).where(ExpenseItem.name == ITEM_NAME))
        await db.commit()
    await engine.dispose()


async def _expense_ledger_count() -> int:
    engine = create_async_engine(settings.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as db:
        n = await db.scalar(
            select(func.count())
            .select_from(CashLedger)
            .where(CashLedger.kind == "expense", CashLedger.amount == Decimal(-AMOUNT))
        )
    await engine.dispose()
    return int(n or 0)


async def test_cash_expense_posts_and_lists(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        item_id = (
            await http.post("/v1/expense-items", headers=admin, json={"name": ITEM_NAME})
        ).json()["id"]

        # A cash expense posts and appears in the day's list.
        created = await http.post(
            "/v1/expenses",
            headers=admin,
            json={"business_date": DAY, "item_id": item_id, "amount": AMOUNT, "method": "cash"},
        )
        assert created.status_code == 201, created.text

        listed = await http.get(f"/v1/expenses?date={DAY}", headers=admin)
        assert listed.status_code == 200
        rows = listed.json()
        assert len(rows) == 1
        assert float(rows[0]["amount"]) == AMOUNT

        # A cash expense also posts a negative cash-ledger entry.
        assert await _expense_ledger_count() == 1
    finally:
        await _cleanup()


async def test_expense_attributed_to_delivery_boy_shows_on_day_sheet(
    client: tuple[AsyncClient, SeededUsers],
) -> None:
    """A per-boy expense reduces his net hand-in on the day sheet."""
    http, users = client
    await _cleanup()
    admin = {"Authorization": f"Bearer {await _token(http, TEST_ADMIN_PHONE)}"}
    try:
        item_id = (
            await http.post("/v1/expense-items", headers=admin, json={"name": ITEM_NAME})
        ).json()["id"]
        created = await http.post(
            "/v1/expenses",
            headers=admin,
            json={
                "business_date": DAY,
                "item_id": item_id,
                "amount": AMOUNT,
                "method": "cash",
                "delivery_id": str(users.delivery_id),
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["delivery_id"] == str(users.delivery_id)
        assert created.json()["delivery_name"] == "Delivery Test"

        sheet = (await http.get(f"/v1/day-sheet/{DAY}", headers=admin)).json()
        row = next(r for r in sheet["rows"] if r["delivery_id"] == str(users.delivery_id))
        assert float(row["expense"]) == AMOUNT
        assert float(row["net"]) == float(row["total"]) - AMOUNT
        assert float(sheet["totals"]["expense"]) == AMOUNT
    finally:
        await _cleanup()
