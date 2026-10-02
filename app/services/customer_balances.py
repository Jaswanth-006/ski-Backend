"""Customer balance service — same charge/repayment ledger as delivery boys, per customer."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CustomerBalance
from app.schemas.customer_balances import (
    CustomerBalanceCreate,
    CustomerBalanceEntryOut,
    CustomerBalanceSummaryOut,
)


class InvalidCustomer(Exception):
    """The referenced customer does not exist."""


def _entry_out(b: CustomerBalance) -> CustomerBalanceEntryOut:
    return CustomerBalanceEntryOut(
        id=b.id,
        customer_id=b.customer_id,
        amount=b.amount,
        entry_date=b.entry_date,
        kind=b.kind,
        note=b.note,
        created_at=b.created_at,
    )


async def create_entry(
    db: AsyncSession, data: CustomerBalanceCreate, created_by: uuid.UUID
) -> CustomerBalanceEntryOut:
    entry = CustomerBalance(
        customer_id=data.customer_id,
        amount=data.amount,
        entry_date=data.entry_date,
        kind=data.kind,
        note=data.note,
        created_by=created_by,
    )
    db.add(entry)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise InvalidCustomer(str(data.customer_id)) from exc
    await db.refresh(entry)
    return _entry_out(entry)


async def list_entries(db: AsyncSession, customer_id: uuid.UUID) -> list[CustomerBalanceEntryOut]:
    stmt = (
        select(CustomerBalance)
        .where(CustomerBalance.customer_id == customer_id)
        .order_by(CustomerBalance.entry_date.desc(), CustomerBalance.created_at.desc())
    )
    return [_entry_out(b) for b in (await db.scalars(stmt)).all()]


_SUMMARY_SQL = text(
    """
    SELECT c.id AS customer_id, c.name AS customer_name,
        COALESCE(SUM(cb.amount) FILTER (WHERE cb.kind = 'charge'), 0)     AS charged,
        COALESCE(SUM(cb.amount) FILTER (WHERE cb.kind = 'repayment'), 0)  AS repaid
    FROM customers c
    LEFT JOIN customer_balances cb ON cb.customer_id = c.id
    WHERE c.is_active = TRUE
    GROUP BY c.id, c.name
    ORDER BY c.name
    """
)


async def summary(db: AsyncSession) -> list[CustomerBalanceSummaryOut]:
    rows = (await db.execute(_SUMMARY_SQL)).mappings().all()
    return [
        CustomerBalanceSummaryOut(
            customer_id=r["customer_id"],
            customer_name=r["customer_name"],
            charged=Decimal(r["charged"]),
            repaid=Decimal(r["repaid"]),
            balance=Decimal(r["charged"]) - Decimal(r["repaid"]),
        )
        for r in rows
    ]


_CHARGES_BY_DAY = text(
    "SELECT customer_id, COALESCE(SUM(amount), 0) AS charged FROM customer_balances "
    "WHERE kind = 'charge' AND entry_date = :on_date GROUP BY customer_id"
)


async def charges_on(db: AsyncSession, on_date: dt.date) -> dict[uuid.UUID, Decimal]:
    """Balance charges created on a date, per customer — for the day sheet."""
    return {
        r["customer_id"]: Decimal(r["charged"])
        for r in (await db.execute(_CHARGES_BY_DAY, {"on_date": on_date})).mappings().all()
    }
