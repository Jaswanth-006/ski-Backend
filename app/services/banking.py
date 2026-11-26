"""Banking master-data service — banks, bank accounts, vendors, people.

Soft-delete only (deactivating hides a bank/account/vendor/person from pickers while keeping
history intact). Balances are each one's opening balance plus the deposits recorded since:
- bank account: opening + money in − money out;
- vendor: opening (paid before the app) + paid through deposits;
- debtor (owes us): opening + given − received; creditor (we owe): opening + received − given.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bank, BankAccount, Person, Vendor
from app.schemas.banking import (
    BankAccountCreate,
    BankAccountOut,
    BankAccountUpdate,
    BankCreate,
    BankUpdate,
    PersonCreate,
    PersonOut,
    PersonUpdate,
    VendorCreate,
    VendorOut,
    VendorUpdate,
)
from app.services.transfers import bank_account_balances, person_flows, vendor_paid


class NameAlreadyExists(Exception):
    """A bank or vendor with the given name already exists."""


class OwnerOnly(Exception):
    """Only the owner can change an opening balance after it was set."""


class InvalidBank(Exception):
    """The referenced bank does not exist."""


def _active_clause(model: Any, active: str) -> ColumnElement[bool]:
    """Filter for the ``active`` query param: "all", "false"/"0", or (default) active only."""
    if active == "all":
        return true()
    return model.is_active.is_(active not in ("false", "0"))  # type: ignore[no-any-return]


# ---- Banks ----
async def list_banks(db: AsyncSession, active: str = "true") -> list[Bank]:
    stmt = select(Bank).where(_active_clause(Bank, active)).order_by(Bank.name)
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
    stmt = stmt.where(_active_clause(BankAccount, active)).order_by(
        Bank.name, BankAccount.account_type
    )
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
            opening_balance=acc.opening_balance,
            balance=acc.opening_balance + balances.get(acc.id, Decimal(0)),
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
        opening_balance=acc.opening_balance,
        balance=acc.opening_balance + balances.get(acc.id, Decimal(0)),
    )


async def create_bank_account(db: AsyncSession, data: BankAccountCreate) -> BankAccountOut:
    if await db.get(Bank, data.bank_id) is None:
        raise InvalidBank(str(data.bank_id))
    row = BankAccount(
        bank_id=data.bank_id,
        account_type=data.account_type,
        label=data.label,
        opening_balance=data.opening_balance,
        is_active=True,
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
    if data.opening_balance is not None:
        row.opening_balance = data.opening_balance
    if data.is_active is not None:
        row.is_active = data.is_active
    await db.commit()
    await db.refresh(row)
    return await _to_account_out(db, row)


# ---- Vendors ----
def _vendor_out(v: Vendor, paid: dict[uuid.UUID, Decimal]) -> VendorOut:
    in_app = paid.get(v.id, Decimal(0))
    return VendorOut(
        id=v.id,
        name=v.name,
        is_active=v.is_active,
        opening_balance=v.opening_balance,
        paid=in_app,
        total_paid=v.opening_balance + in_app,
    )


async def list_vendors(db: AsyncSession, active: str = "true") -> list[VendorOut]:
    stmt = select(Vendor).where(_active_clause(Vendor, active)).order_by(Vendor.name)
    paid = await vendor_paid(db)
    return [_vendor_out(v, paid) for v in await db.scalars(stmt)]


async def create_vendor(db: AsyncSession, data: VendorCreate) -> VendorOut:
    row = Vendor(name=data.name, opening_balance=data.opening_balance, is_active=True)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise NameAlreadyExists(data.name) from exc
    await db.refresh(row)
    return _vendor_out(row, {})


async def update_vendor(
    db: AsyncSession, vendor_id: uuid.UUID, data: VendorUpdate
) -> VendorOut | None:
    row = await db.get(Vendor, vendor_id)
    if row is None:
        return None
    if data.name is not None:
        row.name = data.name
    if data.opening_balance is not None:
        row.opening_balance = data.opening_balance
    if data.is_active is not None:
        row.is_active = data.is_active
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise NameAlreadyExists(data.name or "") from exc
    await db.refresh(row)
    return _vendor_out(row, await vendor_paid(db))


# ---- People (debtors / creditors) ----
def _person_out(p: Person, flows: dict[uuid.UUID, tuple[Decimal, Decimal]]) -> PersonOut:
    given, received = flows.get(p.id, (Decimal(0), Decimal(0)))
    if p.kind == "debtor":
        balance = p.opening_balance + given - received
    else:
        balance = p.opening_balance + received - given
    return PersonOut(
        id=p.id,
        name=p.name,
        kind=p.kind,
        phone=p.phone,
        note=p.note,
        is_active=p.is_active,
        opening_balance=p.opening_balance,
        given=given,
        received=received,
        balance=balance,
        created_at=p.created_at,
    )


async def list_people(
    db: AsyncSession, active: str = "true", kind: str | None = None
) -> list[PersonOut]:
    stmt = select(Person).where(_active_clause(Person, active))
    if kind is not None:
        stmt = stmt.where(Person.kind == kind)
    flows = await person_flows(db)
    return [_person_out(p, flows) for p in await db.scalars(stmt.order_by(Person.name))]


async def create_person(db: AsyncSession, data: PersonCreate) -> PersonOut:
    row = Person(
        name=data.name,
        kind=data.kind,
        phone=data.phone,
        note=data.note,
        opening_balance=data.opening_balance,
        is_active=True,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise NameAlreadyExists(data.name) from exc
    await db.refresh(row)
    return _person_out(row, {})


async def update_person(
    db: AsyncSession, person_id: uuid.UUID, data: PersonUpdate, *, is_owner: bool
) -> PersonOut | None:
    row = await db.get(Person, person_id)
    if row is None:
        return None
    if (
        data.opening_balance is not None
        and data.opening_balance != row.opening_balance
        and not is_owner
    ):
        raise OwnerOnly()
    if data.name is not None:
        row.name = data.name.strip()
    if data.phone is not None:
        row.phone = data.phone or None
    if data.note is not None:
        row.note = data.note or None
    if data.opening_balance is not None:
        row.opening_balance = data.opening_balance
    if data.is_active is not None:
        row.is_active = data.is_active
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise NameAlreadyExists(data.name or "") from exc
    await db.refresh(row)
    return _person_out(row, await person_flows(db))
