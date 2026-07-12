"""Credit (receivables) service (Phase E)."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Credit
from app.schemas.credits import CreditCreate, CreditOut


class CreditNotFound(Exception):
    """No credit with that id."""


def _out(c: Credit) -> CreditOut:
    return CreditOut(
        id=c.id,
        person_name=c.person_name,
        amount=c.amount,
        given_date=c.given_date,
        note=c.note,
        is_settled=c.is_settled,
        settled_date=c.settled_date,
        created_at=c.created_at,
    )


async def list_credits(db: AsyncSession, *, settled: bool | None = None) -> list[CreditOut]:
    stmt = select(Credit)
    if settled is not None:
        stmt = stmt.where(Credit.is_settled.is_(settled))
    # Open ones first, newest given date first.
    stmt = stmt.order_by(Credit.is_settled, Credit.given_date.desc())
    return [_out(c) for c in (await db.scalars(stmt)).all()]


async def create_credit(db: AsyncSession, data: CreditCreate, created_by: uuid.UUID) -> CreditOut:
    credit = Credit(
        person_name=data.person_name.strip(),
        amount=data.amount,
        given_date=data.given_date,
        note=data.note,
        created_by=created_by,
    )
    db.add(credit)
    await db.commit()
    await db.refresh(credit)
    return _out(credit)


async def settle_credit(db: AsyncSession, credit_id: uuid.UUID, *, settled: bool) -> CreditOut:
    credit = await db.get(Credit, credit_id)
    if credit is None:
        raise CreditNotFound(str(credit_id))
    credit.is_settled = settled
    credit.settled_date = dt.date.today() if settled else None
    await db.commit()
    await db.refresh(credit)
    return _out(credit)
