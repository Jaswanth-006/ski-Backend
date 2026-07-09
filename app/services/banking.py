"""Banking master-data service (Phase 8-B).

Soft-delete only (deactivating hides a bank/account/vendor from pickers while keeping
history intact). Everything is fully editable.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bank, BankAccount, Vendor
from app.schemas.banking import (
    BankAccountCreate,
    BankAccountOut,
    BankAccountUpdate,
    BankCreate,
    BankUpdate,
    VendorCreate,
    VendorUpdate,
)
from app.services.transfers import bank_account_balances


class NameAlreadyExists(Exception):
    """A bank or vendor with the given name already exists."""


class InvalidBank(Exception):
    """The referenced bank does not exist."""


def _active_filter(stmt: Select[Any], model: Any, active: str) -> Select[Any]:
    if active == "all":
        return stmt
    if active in ("false", "0"):
        return stmt.where(model.is_active.is_(False))
    return stmt.where(model.is_active.is_(True))


# ---- Banks ----
async def list_banks(db: AsyncSession, active: str = "true") -> list[Bank]:
    stmt = _active_filter(select(Bank), Bank, active).order_by(Bank.name)
    return list(await db.scalars(stmt))


async def create_bank(db: AsyncSession, data: BankCreate) -> Bank:
    row = Bank(name=data.name, is_active=True)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise NameAlreadyExists(data.name) from exc
    await db.refresh(row)
    return row


async def update_bank(db: AsyncSession, bank_id: uuid.UUID, data: BankUpdate) -> Bank | None:
    row = await db.get(Bank, bank_id)
    if row is None:
        return None
    if data.name is not None:
        row.name = data.name
    if data.is_active is not None:
        row.is_active = data.is_active
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise NameAlreadyExists(data.name or "") from exc
    await db.refresh(row)
    return row


# ---- Bank accounts ----
async def list_bank_accounts(db: AsyncSession, active: str = "true") -> list[BankAccountOut]:
    stmt = select(BankAccount, Bank.name).join(Bank, Bank.id == BankAccount.bank_id)
    stmt = _active_filter(stmt, BankAccount, active).order_by(Bank.name, BankAccount.account_type)
    rows = (await db.execute(stmt)).all()
    balances = await bank_account_balances(db)
    return [
        BankAccountOut(
            id=acc.id,
            bank_id=acc.bank_id,
            bank_name=bank_name,
            account_type=acc.account_type,
            label=acc.label,
            is_active=acc.is_active,
            balance=balances.get(acc.id, Decimal(0)),
        )
        for acc, bank_name in rows
    ]


async def _to_account_out(db: AsyncSession, acc: BankAccount) -> BankAccountOut:
    bank_name = await db.scalar(select(Bank.name).where(Bank.id == acc.bank_id))
    balances = await bank_account_balances(db)
    return BankAccountOut(
        id=acc.id,
        bank_id=acc.bank_id,
        bank_name=bank_name or "—",
        account_type=acc.account_type,
        label=acc.label,
        is_active=acc.is_active,
        balance=balances.get(acc.id, Decimal(0)),
    )


async def create_bank_account(db: AsyncSession, data: BankAccountCreate) -> BankAccountOut:
    if await db.get(Bank, data.bank_id) is None:
        raise InvalidBank(str(data.bank_id))
    row = BankAccount(
        bank_id=data.bank_id, account_type=data.account_type, label=data.label, is_active=True
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return await _to_account_out(db, row)


async def update_bank_account(
    db: AsyncSession, account_id: uuid.UUID, data: BankAccountUpdate
) -> BankAccountOut | None:
    row = await db.get(BankAccount, account_id)
    if row is None:
        return None
    if data.account_type is not None:
        row.account_type = data.account_type
    if data.label is not None:
        row.label = data.label
    if data.is_active is not None:
        row.is_active = data.is_active
    await db.commit()
    await db.refresh(row)
    return await _to_account_out(db, row)


# ---- Vendors ----
async def list_vendors(db: AsyncSession, active: str = "true") -> list[Vendor]:
    stmt = _active_filter(select(Vendor), Vendor, active).order_by(Vendor.name)
    return list(await db.scalars(stmt))


async def create_vendor(db: AsyncSession, data: VendorCreate) -> Vendor:
    row = Vendor(name=data.name, is_active=True)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise NameAlreadyExists(data.name) from exc
    await db.refresh(row)
    return row


async def update_vendor(
    db: AsyncSession, vendor_id: uuid.UUID, data: VendorUpdate
) -> Vendor | None:
    row = await db.get(Vendor, vendor_id)
    if row is None:
        return None
    if data.name is not None:
        row.name = data.name
    if data.is_active is not None:
        row.is_active = data.is_active
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise NameAlreadyExists(data.name or "") from exc
    await db.refresh(row)
    return row
