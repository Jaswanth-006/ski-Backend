"""Sales + reconciliation + the Move-to-Day-Sheet transaction (01-BACKEND-PRD §6, §7).

In v1 (web entry) a sale is created and posted in one ACID transaction: resolve+snapshot
the temporal price, deduct inventory under a row lock, append the stock and cash ledgers,
run reconciliation, and write the audit row. Any failure rolls the whole thing back, so a
rejected sale leaves zero side effects.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CashDenomination,
    CashLedger,
    Customer,
    CylinderType,
    DaySheetStatus,
    DeliveryBalance,
    Inventory,
    Sale,
    SaleLine,
    StockLedger,
    User,
)
from app.schemas.sales import SaleCreate, SaleLineOut, SaleOut
from app.services import audit, delivery_other_sales, pricing


class DayClosed(Exception):
    """The business date's day sheet is already closed."""


class NoPriceForDate(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(f"no price set for {code} on that date")


class InsufficientStock(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"insufficient stock for {code}")


class ReconciliationFailed(Exception):
    def __init__(self, flags: list[str]) -> None:
        self.flags = flags
        super().__init__("; ".join(flags))


def reconcile(
    revenue: Decimal,
    cash_total: Decimal,
    upi_total: Decimal,
    online_total: Decimal,
    balance_total: Decimal,
) -> list[str]:
    """Revenue tally: Σ(qty × unit_price) == cash + UPI + online + balance (01-BACKEND-PRD §7).

    Online is paid straight to the company; balance is the part the boy didn't hand over
    (added to what he owes). Cash + UPI is what he physically settles.
    """
    flags: list[str] = []
    collected = cash_total + upi_total + online_total + balance_total
    if collected != revenue:
        flags.append(
            f"revenue mismatch: sold {revenue} but accounted {collected} "
            f"(cash {cash_total} + upi {upi_total} + online {online_total} "
            f"+ balance {balance_total})"
        )
    return flags


async def _assert_day_open(db: AsyncSession, business_date: dt.date) -> None:
    status = await db.get(DaySheetStatus, business_date)
    if status is not None and status.is_closed:
        raise DayClosed()


async def create_and_post_sale(
    db: AsyncSession, data: SaleCreate, idempotency_key: uuid.UUID, actor: User
) -> SaleOut:
    # Idempotency: a repeat with the same key returns the original sale (00-MAIN §7).
    existing = await db.scalar(select(Sale).where(Sale.idempotency_key == idempotency_key))
    if existing is not None:
        return await _build_sale_out(db, existing)

    await _assert_day_open(db, data.business_date)

    sale = Sale(
        idempotency_key=idempotency_key,
        delivery_id=data.delivery_id,
        customer_id=data.customer_id,
        business_date=data.business_date,
        status="pending",
        upi_total=data.upi_total,
        online_total=data.online_total,
        balance_total=data.balance_total,
        submitted_via="web",
    )
    db.add(sale)
    await db.flush()  # get sale.id

    # The boy's per-cylinder extra rides on top of the fixed price (delivery sales only).
    boy_extra = (
        await delivery_other_sales.amount_for(db, data.delivery_id)
        if data.delivery_id is not None
        else Decimal(0)
    )

    revenue = Decimal(0)
    for line in data.lines:
        unit_price = await pricing.resolve_unit_price(db, line.cylinder_type_id, data.business_date)
        if unit_price is None:
            ct = await db.get(CylinderType, line.cylinder_type_id)
            raise NoPriceForDate(ct.code if ct else str(line.cylinder_type_id))

        inv = await db.scalar(
            select(Inventory)
            .where(Inventory.cylinder_type_id == line.cylinder_type_id)
            .with_for_update()
        )
        if inv is None or inv.quantity < line.qty:
            ct = await db.get(CylinderType, line.cylinder_type_id)
            raise InsufficientStock(ct.code if ct else str(line.cylinder_type_id))
        inv.quantity -= line.qty
        inv.version += 1

        # Empties returned default to the number sold, but can differ.
        empty_qty = line.empty_qty if line.empty_qty is not None else line.qty
        db.add(
            SaleLine(
                sale_id=sale.id,
                cylinder_type_id=line.cylinder_type_id,
                qty=line.qty,
                empty_qty=empty_qty,
                unit_price=unit_price,
                other_sales_per_unit=boy_extra,
            )
        )
        # Full goes out; empties come back (as many as were actually returned).
        db.add(
            StockLedger(
                cylinder_type_id=line.cylinder_type_id,
                condition="full",
                delta=-line.qty,
                reason="sale",
                business_date=data.business_date,
                ref_id=sale.id,
                created_by=actor.id,
            )
        )
        if empty_qty:
            db.add(
                StockLedger(
                    cylinder_type_id=line.cylinder_type_id,
                    condition="empty",
                    delta=empty_qty,
                    reason="sale",
                    business_date=data.business_date,
                    ref_id=sale.id,
                    created_by=actor.id,
                )
            )
        revenue += (unit_price + boy_extra) * line.qty

    cash_total = Decimal(0)
    for denom in data.denominations:
        db.add(
            CashDenomination(
                sale_id=sale.id, note_value=denom.note_value, note_count=denom.note_count
            )
        )
        cash_total += Decimal(denom.note_value * denom.note_count)

    flags = reconcile(revenue, cash_total, data.upi_total, data.online_total, data.balance_total)
    if flags and actor.role != "super_admin":
        raise ReconciliationFailed(flags)

    db.add(CashLedger(sale_id=sale.id, amount=cash_total, kind="cash"))
    db.add(CashLedger(sale_id=sale.id, amount=data.upi_total, kind="upi"))
    if data.online_total:
        db.add(CashLedger(sale_id=sale.id, amount=data.online_total, kind="online"))
    # The uncollected balance is money the delivery boy owes → his balance ledger.
    if data.balance_total and data.delivery_id is not None:
        db.add(
            DeliveryBalance(
                delivery_id=data.delivery_id,
                amount=data.balance_total,
                entry_date=data.business_date,
                kind="charge",
                note="sale balance (uncollected)",
                created_by=actor.id,
            )
        )

    sale.status = "approved"
    sale.approved_by = actor.id
    sale.approved_at = dt.datetime.now(tz=dt.UTC)

    await audit.write(
        db,
        actor.id,
        "sale.post",
        "sale",
        sale.id,
        new={
            "delivery_id": str(data.delivery_id),
            "business_date": str(data.business_date),
            "revenue": str(revenue),
            "cash": str(cash_total),
            "upi": str(data.upi_total),
            "online": str(data.online_total),
            "balance": str(data.balance_total),
            "override": bool(flags),
        },
    )

    await db.commit()
    return await _build_sale_out(db, sale)


async def _build_sale_out(db: AsyncSession, sale: Sale) -> SaleOut:
    line_rows = (
        await db.execute(
            select(SaleLine, CylinderType.code, CylinderType.label)
            .join(CylinderType, CylinderType.id == SaleLine.cylinder_type_id)
            .where(SaleLine.sale_id == sale.id)
            .order_by(CylinderType.code)
        )
    ).all()
    lines = [
        SaleLineOut(
            cylinder_type_id=sl.cylinder_type_id,
            code=code,
            label=label,
            qty=sl.qty,
            empty_qty=sl.empty_qty,
            unit_price=sl.unit_price,
            other_sales_per_unit=sl.other_sales_per_unit,
            line_total=(sl.unit_price + sl.other_sales_per_unit) * sl.qty,
        )
        for sl, code, label in line_rows
    ]
    revenue_total = sum((line.line_total for line in lines), Decimal(0))

    cash_total = await db.scalar(
        select(CashLedger.amount).where(CashLedger.sale_id == sale.id, CashLedger.kind == "cash")
    ) or Decimal(0)

    if sale.customer_id is not None:
        party_kind = "customer"
        party_name = (
            await db.scalar(select(Customer.name).where(Customer.id == sale.customer_id)) or "—"
        )
    else:
        party_kind = "delivery"
        party_name = await db.scalar(select(User.name).where(User.id == sale.delivery_id)) or "—"

    return SaleOut(
        id=sale.id,
        delivery_id=sale.delivery_id,
        customer_id=sale.customer_id,
        party_kind=party_kind,
        party_name=party_name,
        business_date=sale.business_date,
        status=sale.status,
        submitted_via=sale.submitted_via,
        created_at=sale.created_at,
        lines=lines,
        cash_total=cash_total,
        upi_total=sale.upi_total,
        online_total=sale.online_total,
        balance_total=sale.balance_total,
        revenue_total=revenue_total,
        settled_total=cash_total + sale.upi_total,
    )


async def list_sales(
    db: AsyncSession, business_date: dt.date | None = None, status: str | None = None
) -> list[SaleOut]:
    stmt = select(Sale)
    if business_date is not None:
        stmt = stmt.where(Sale.business_date == business_date)
    if status is not None:
        stmt = stmt.where(Sale.status == status)
    sales = list(await db.scalars(stmt.order_by(Sale.created_at.desc())))
    return [await _build_sale_out(db, sale) for sale in sales]


async def get_sale(db: AsyncSession, sale_id: uuid.UUID) -> SaleOut | None:
    sale = await db.get(Sale, sale_id)
    if sale is None:
        return None
    return await _build_sale_out(db, sale)
