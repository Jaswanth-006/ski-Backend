"""Customer catalog service (Phase I)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Customer
from app.schemas.customer import CustomerOut, CustomerUpdate


class DuplicateCustomer(Exception):
    """A customer with this name already exists."""


class CustomerNotFound(Exception):
    """No customer with that id."""


def _out(c: Customer) -> CustomerOut:
    return CustomerOut(id=c.id, name=c.name, is_active=c.is_active)


async def list_customers(db: AsyncSession, *, active_only: bool = True) -> list[CustomerOut]:
    stmt = select(Customer).order_by(Customer.name)
    if active_only:
        stmt = stmt.where(Customer.is_active.is_(True))
    return [_out(c) for c in (await db.scalars(stmt)).all()]


async def create_customer(db: AsyncSession, name: str) -> CustomerOut:
    customer = Customer(name=name.strip())
    db.add(customer)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateCustomer(name) from exc
    await db.refresh(customer)
    return _out(customer)


async def update_customer(
    db: AsyncSession, customer_id: uuid.UUID, data: CustomerUpdate
) -> CustomerOut:
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise CustomerNotFound(str(customer_id))
    if data.name is not None:
        customer.name = data.name.strip()
    if data.is_active is not None:
        customer.is_active = data.is_active
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateCustomer(data.name or "") from exc
    await db.refresh(customer)
    return _out(customer)
