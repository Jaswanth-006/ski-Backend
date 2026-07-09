"""Deposit / transfer service (Phase 8-C).

Records money moving out of a source (cashier box or bank account) to a destination
(vendor, person, or own bank account). Bank-account balances are derived from these rows;
the cashier box (services/cashier_box.py) subtracts box-sourced transfers. Insufficient
balance is allowed (accounting, not real banking) — the UI simply warns.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bank, BankAccount, Transfer, Vendor
from app.schemas.transfers import TransferCreate, TransferOut
from app.services import audit


class InvalidReference(Exception):
    """A referenced bank account or vendor does not exist."""


async def _account_label(db: AsyncSession, account_id: uuid.UUID) -> str:
    row = (
        await db.execute(
            select(Bank.name, BankAccount.account_type, BankAccount.label)
            .join(BankAccount, BankAccount.bank_id == Bank.id)
            .where(BankAccount.id == account_id)
        )
    ).first()
    if row is None:
        return "—"
    bank_name, account_type, label = row
    return f"{bank_name} · {account_type}" + (f" ({label})" if label else "")


async def _source_label(db: AsyncSession, t: Transfer) -> str:
    if t.source_kind == "cashier_box":
        return "Cashier box"
    assert t.source_bank_account_id is not None
    return await _account_label(db, t.source_bank_account_id)


async def _dest_label(db: AsyncSession, t: Transfer) -> str:
    if t.dest_kind == "vendor":
        assert t.dest_vendor_id is not None
        name = await db.scalar(select(Vendor.name).where(Vendor.id == t.dest_vendor_id))
        return name or "—"
    if t.dest_kind == "bank_account":
        assert t.dest_bank_account_id is not None
        return await _account_label(db, t.dest_bank_account_id)
    return t.dest_person_name or "—"


async def _to_out(db: AsyncSession, t: Transfer) -> TransferOut:
    return TransferOut(
        id=t.id,
        business_date=t.business_date,
        amount=t.amount,
        source_kind=t.source_kind,
        source_label=await _source_label(db, t),
        dest_kind=t.dest_kind,
        dest_label=await _dest_label(db, t),
        method=t.method,
        note=t.note,
        created_at=t.created_at,
    )


async def create_transfer(
    db: AsyncSession, data: TransferCreate, actor_id: uuid.UUID
) -> TransferOut:
    # Validate referenced entities exist.
    if data.source_kind == "bank_account":
        if await db.get(BankAccount, data.source_bank_account_id) is None:
            raise InvalidReference("source account")
    if data.dest_kind == "vendor" and await db.get(Vendor, data.dest_vendor_id) is None:
        raise InvalidReference("vendor")
    if (
        data.dest_kind == "bank_account"
        and await db.get(BankAccount, data.dest_bank_account_id) is None
    ):
        raise InvalidReference("destination account")

    t = Transfer(
        business_date=data.business_date,
        amount=data.amount,
        source_kind=data.source_kind,
        source_bank_account_id=data.source_bank_account_id,
        dest_kind=data.dest_kind,
        dest_vendor_id=data.dest_vendor_id,
        dest_bank_account_id=data.dest_bank_account_id,
        dest_person_name=data.dest_person_name,
        method=data.method,
        note=data.note,
        created_by=actor_id,
    )
    db.add(t)
    await db.flush()
    await audit.write(
        db,
        actor_id,
        "transfer.create",
        "transfer",
        t.id,
        new={"amount": str(data.amount), "source": data.source_kind, "dest": data.dest_kind},
    )
    await db.commit()
    await db.refresh(t)
    return await _to_out(db, t)


async def list_transfers(
    db: AsyncSession, start: dt.date | None = None, end: dt.date | None = None
) -> list[TransferOut]:
    stmt = select(Transfer)
    if start is not None:
        stmt = stmt.where(Transfer.business_date >= start)
    if end is not None:
        stmt = stmt.where(Transfer.business_date <= end)
    rows = list(await db.scalars(stmt.order_by(Transfer.created_at.desc())))
    return [await _to_out(db, t) for t in rows]


async def bank_account_balances(db: AsyncSession) -> dict[uuid.UUID, Decimal]:
    """Per-account running balance = money in (transfers into it) − money out."""
    balances: dict[uuid.UUID, Decimal] = {}
    into = await db.execute(
        select(Transfer.dest_bank_account_id, func.sum(Transfer.amount))
        .where(Transfer.dest_kind == "bank_account")
        .group_by(Transfer.dest_bank_account_id)
    )
    for acc_id, total in into:
        if acc_id is not None:
            balances[acc_id] = Decimal(total)
    out = await db.execute(
        select(Transfer.source_bank_account_id, func.sum(Transfer.amount))
        .where(Transfer.source_kind == "bank_account")
        .group_by(Transfer.source_bank_account_id)
    )
    for acc_id, total in out:
        if acc_id is not None:
            balances[acc_id] = balances.get(acc_id, Decimal(0)) - Decimal(total)
    return balances
