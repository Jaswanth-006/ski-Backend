"""Delivery-boy balance service (Phase K)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DeliveryBalance, User
from app.schemas.delivery_balances import (
    DeliveryBalanceCreate,
    DeliveryBalanceEntryOut,
    DeliveryBalanceSummaryOut,
)
from app.services import audit


def _entry_out(b: DeliveryBalance) -> DeliveryBalanceEntryOut:
    return DeliveryBalanceEntryOut(
        id=b.id,
        delivery_id=b.delivery_id,
        amount=b.amount,
        entry_date=b.entry_date,
        kind=b.kind,
        note=b.note,
        method=b.method,
        created_at=b.created_at,
    )


class InvalidDeliveryPerson(Exception):
    """The id is not a delivery person."""


async def create_entry(
    db: AsyncSession, data: DeliveryBalanceCreate, created_by: uuid.UUID
) -> DeliveryBalanceEntryOut:
    person = await db.get(User, data.delivery_id)
    if person is None or person.role != "delivery":
        raise InvalidDeliveryPerson(str(data.delivery_id))
    entry = DeliveryBalance(
        delivery_id=data.delivery_id,
        amount=data.amount,
        entry_date=data.entry_date,
        kind=data.kind,
        note=data.note,
        method=data.method,
        created_by=created_by,
    )
    db.add(entry)
    await audit.write(
        db,
        created_by,
        f"delivery_balance.{data.kind}",
        "delivery_balance",
        data.delivery_id,
        new={
            "amount": str(data.amount),
            "entry_date": str(data.entry_date),
            "method": data.method,
            "note": data.note,
        },
    )
    await db.commit()
    await db.refresh(entry)
    return _entry_out(entry)


async def list_entries(db: AsyncSession, delivery_id: uuid.UUID) -> list[DeliveryBalanceEntryOut]:
    stmt = (
        select(DeliveryBalance)
        .where(DeliveryBalance.delivery_id == delivery_id)
        .order_by(DeliveryBalance.entry_date.desc(), DeliveryBalance.created_at.desc())
    )
    return [_entry_out(b) for b in (await db.scalars(stmt)).all()]


_SUMMARY_SQL = text(
    """
    SELECT u.id AS delivery_id, u.name AS delivery_name,
        COALESCE(SUM(db.amount) FILTER (WHERE db.kind = 'charge'), 0)     AS charged,
        COALESCE(SUM(db.amount) FILTER (WHERE db.kind = 'repayment'), 0)  AS repaid
    FROM users u
    LEFT JOIN delivery_balances db ON db.delivery_id = u.id
    WHERE u.role = 'delivery'
    GROUP BY u.id, u.name, u.is_active
    -- deactivated staff stay listed while they still owe something
    HAVING u.is_active
        OR COALESCE(SUM(db.amount) FILTER (WHERE db.kind = 'charge'), 0)
         - COALESCE(SUM(db.amount) FILTER (WHERE db.kind = 'repayment'), 0) <> 0
    ORDER BY u.name
    """
)


async def summary(db: AsyncSession) -> list[DeliveryBalanceSummaryOut]:
    rows = (await db.execute(_SUMMARY_SQL)).mappings().all()
    return [
        DeliveryBalanceSummaryOut(
            delivery_id=r["delivery_id"],
            delivery_name=r["delivery_name"],
            charged=Decimal(r["charged"]),
            repaid=Decimal(r["repaid"]),
            balance=Decimal(r["charged"]) - Decimal(r["repaid"]),
        )
        for r in rows
    ]


_CHARGES_BY_DAY = text(
    "SELECT delivery_id, COALESCE(SUM(amount), 0) AS charged FROM delivery_balances "
    "WHERE kind = 'charge' AND entry_date = :on_date GROUP BY delivery_id"
)


async def charges_on(db: AsyncSession, on_date: dt.date) -> dict[uuid.UUID, Decimal]:
    """Balance charges created on a date, per delivery boy — for the day sheet."""
    return {
        r["delivery_id"]: Decimal(r["charged"])
        for r in (await db.execute(_CHARGES_BY_DAY, {"on_date": on_date})).mappings().all()
    }
