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

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CashDenomination,
    CashLedger,
    Customer,
    CustomerBalance,
    CylinderType,
    DaySheetStatus,
    DeliveryBalance,
    Expense,
    ExpenseItem,
    Inventory,
    Sale,
    SaleLine,
    StockLedger,
    User,
)
from app.schemas.sales import (
    DenominationIn,
    SaleCreate,
    SaleExpenseOut,
    SaleLineOut,
    SaleOut,
)
from app.services import audit, delivery_other_sales, pricing

# Note prefix on the balance charge a sale writes for its uncollected part (reports match on it).
SALE_CHARGE_NOTE = "sale balance (uncollected)"


class SaleError(Exception):
    """Base for the sale errors the API turns into 4xx responses."""


class DuplicateInvoice(SaleError):
    def __init__(self, invoice_no: str) -> None:
        self.invoice_no = invoice_no
        super().__init__(f"invoice number {invoice_no} is already used")


class DayClosed(SaleError):
    """The business date's day sheet is already closed."""

    def __init__(self, owner_can_change: bool = False) -> None:
        self.owner_can_change = owner_can_change
        super().__init__("the day sheet is closed")


class NoPriceForDate(SaleError):
    def __init__(self, code: str) -> None:
        super().__init__(f"no price set for {code} on that date")


class InsufficientStock(SaleError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"insufficient stock for {code}")


class ReconciliationFailed(SaleError):
    def __init__(self, flags: list[str]) -> None:
        self.flags = flags
        super().__init__("; ".join(flags))


def reconcile(
    revenue: Decimal,
    cash_total: Decimal,
    upi_total: Decimal,
    online_total: Decimal,
    balance_total: Decimal,
    expenses_total: Decimal = Decimal(0),
) -> list[str]:
    """Revenue tally: Σ(qty × unit_price) == cash + UPI + online + balance + route expenses.

    Online is paid straight to the company; route expenses were spent by the boy out of the
    collection; balance is the part he didn't hand over (added to what he owes). Cash + UPI is
    what he physically settles.
    """
    flags: list[str] = []
    collected = cash_total + upi_total + online_total + balance_total + expenses_total
    if collected != revenue:
        flags.append(
            f"revenue mismatch: sold {revenue} but accounted {collected} "
            f"(cash {cash_total} + upi {upi_total} + online {online_total} "
            f"+ balance {balance_total} + expenses {expenses_total})"
        )
    return flags


class InvalidParty(SaleError):
    """The delivery person / customer / expense item on the sale does not exist."""


class SaleNotFound(SaleError):
    pass


class SaleNotCancellable(SaleError):
    """Only a posted (approved) sale can be cancelled or edited."""


async def _is_closed(db: AsyncSession, business_date: dt.date) -> bool:
    status = await db.get(DaySheetStatus, business_date)
    return status is not None and status.is_closed


async def _assert_day_open(db: AsyncSession, business_date: dt.date, actor: User) -> None:
    """A closed day takes no new or changed sales — except from the owner."""
    if actor.role != "super_admin" and await _is_closed(db, business_date):
        raise DayClosed(owner_can_change=True)


async def create_and_post_sale(
    db: AsyncSession, data: SaleCreate, idempotency_key: uuid.UUID, actor: User
) -> SaleOut:
    # Idempotency: a repeat with the same key returns the original sale (00-MAIN §7).
    existing = await db.scalar(select(Sale).where(Sale.idempotency_key == idempotency_key))
    if existing is not None:
        return await _build_sale_out(db, existing)

    if await _is_closed(db, data.business_date):
        raise DayClosed()
    sale = await _post(db, data, idempotency_key, actor)
    await _commit(db, data.invoice_no)
    return await _build_sale_out(db, sale)


async def cancel_sale(db: AsyncSession, sale_id: uuid.UUID, reason: str, actor: User) -> SaleOut:
    sale = await _load_for_change(db, sale_id, actor)
    await _reverse(db, sale, reason, actor)
    await db.commit()
    return await _build_sale_out(db, sale)


async def replace_sale(
    db: AsyncSession,
    sale_id: uuid.UUID,
    reason: str,
    data: SaleCreate,
    idempotency_key: uuid.UUID,
    actor: User,
) -> SaleOut:
    """Edit = cancel the old sale and post the corrected one, in one transaction."""
    existing = await db.scalar(select(Sale).where(Sale.idempotency_key == idempotency_key))
    if existing is not None:
        return await _build_sale_out(db, existing)

    old = await _load_for_change(db, sale_id, actor)
    await _assert_day_open(db, data.business_date, actor)
    await _reverse(db, old, reason, actor)
    new = await _post(db, data, idempotency_key, actor)
    await audit.write(
        db,
        actor.id,
        "sale.edit",
        "sale",
        new.id,
        old={"sale_id": str(old.id), "invoice_no": old.invoice_no},
        new={"sale_id": str(new.id), "invoice_no": new.invoice_no, "reason": reason},
    )
    await _commit(db, data.invoice_no)
    return await _build_sale_out(db, new)


async def _load_for_change(db: AsyncSession, sale_id: uuid.UUID, actor: User) -> Sale:
    sale = await db.scalar(select(Sale).where(Sale.id == sale_id).with_for_update())
    if sale is None:
        raise SaleNotFound()
    if sale.status != "approved":
        raise SaleNotCancellable()
    await _assert_day_open(db, sale.business_date, actor)
    return sale


async def _reverse(db: AsyncSession, sale: Sale, reason: str, actor: User) -> None:
    """Undo everything a posted sale did: stock back, its balance charge gone, marked cancelled.

    Its cash / UPI / online rows stay but every sheet, report and the cashier box only count
    approved sales, so they drop out with the status change.
    """
    lines = (await db.scalars(select(SaleLine).where(SaleLine.sale_id == sale.id))).all()
    note = f"cancelled · invoice {sale.invoice_no}"
    for line in lines:
        inv = await db.scalar(
            select(Inventory)
            .where(Inventory.cylinder_type_id == line.cylinder_type_id)
            .with_for_update()
        )
        if inv is not None:
            inv.quantity += line.qty
            inv.version += 1
        # Opposite 'sale' rows on the same date net the sale out of every stock figure.
        db.add(
            StockLedger(
                cylinder_type_id=line.cylinder_type_id,
                condition="full",
                delta=line.qty,
                reason="sale",
                business_date=sale.business_date,
                ref_id=sale.id,
                note=note,
                created_by=actor.id,
            )
        )
        if line.empty_qty:
            db.add(
                StockLedger(
                    cylinder_type_id=line.cylinder_type_id,
                    condition="empty",
                    delta=-line.empty_qty,
                    reason="sale",
                    business_date=sale.business_date,
                    ref_id=sale.id,
                    note=note,
                    created_by=actor.id,
                )
            )

    await db.execute(delete(Expense).where(Expense.sale_id == sale.id))
    await db.execute(delete(DeliveryBalance).where(DeliveryBalance.sale_id == sale.id))
    await db.execute(delete(CustomerBalance).where(CustomerBalance.sale_id == sale.id))

    sale.status = "cancelled"
    sale.cancelled_at = dt.datetime.now(tz=dt.UTC)
    sale.cancelled_by = actor.id
    sale.cancel_reason = reason
    await audit.write(
        db,
        actor.id,
        "sale.cancel",
        "sale",
        sale.id,
        old={
            "invoice_no": sale.invoice_no,
            "business_date": str(sale.business_date),
            "upi": str(sale.upi_total),
            "online": str(sale.online_total),
            "balance": str(sale.balance_total),
        },
        new={"status": "cancelled", "reason": reason},
    )
    # Flush now so the invoice number is free for a re-posted sale in the same transaction.
    await db.flush()


async def _commit(db: AsyncSession, invoice_no: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        # Lost a race with another sale using the same invoice number.
        await db.rollback()
        if "uq_sales_invoice_no" in str(exc.orig):
            raise DuplicateInvoice(invoice_no) from exc
        raise


async def _post(
    db: AsyncSession, data: SaleCreate, idempotency_key: uuid.UUID, actor: User
) -> Sale:
    """Build and post a sale (no commit). The caller has already checked the day is open."""
    taken = await db.scalar(
        select(Sale.id).where(Sale.invoice_no == data.invoice_no, Sale.status != "cancelled")
    )
    if taken is not None:
        raise DuplicateInvoice(data.invoice_no)
    if data.delivery_id is not None:
        person = await db.get(User, data.delivery_id)
        if person is None or person.role != "delivery":
            raise InvalidParty("delivery person not found")
    elif await db.get(Customer, data.customer_id) is None:
        raise InvalidParty("customer not found")
    for e in data.expenses:
        if await db.get(ExpenseItem, e.item_id) is None:
            raise InvalidParty("expense item not found")

    sale = Sale(
        idempotency_key=idempotency_key,
        invoice_no=data.invoice_no,
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
                damaged_qty=line.damaged_qty,
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

    expenses_total = sum((e.amount for e in data.expenses), Decimal(0))
    flags = reconcile(
        revenue, cash_total, data.upi_total, data.online_total, data.balance_total, expenses_total
    )
    if flags:
        # No override: an unbalanced sale would leave money unaccounted for.
        raise ReconciliationFailed(flags)

    # Route expenses: recorded as expenses, but they never pass through the cashier box.
    for e in data.expenses:
        db.add(
            Expense(
                business_date=data.business_date,
                item_id=e.item_id,
                amount=e.amount,
                method="cash",
                note=f"route · invoice {data.invoice_no}",
                delivery_id=data.delivery_id,
                sale_id=sale.id,
                created_by=actor.id,
            )
        )

    db.add(CashLedger(sale_id=sale.id, amount=cash_total, kind="cash"))
    db.add(CashLedger(sale_id=sale.id, amount=data.upi_total, kind="upi"))
    if data.online_total:
        db.add(CashLedger(sale_id=sale.id, amount=data.online_total, kind="online"))
    # The uncollected balance is money the delivery boy / customer owes → their balance ledger.
    if data.balance_total:
        note = f"{SALE_CHARGE_NOTE} · invoice {data.invoice_no}"
        if data.delivery_id is not None:
            db.add(
                DeliveryBalance(
                    delivery_id=data.delivery_id,
                    amount=data.balance_total,
                    entry_date=data.business_date,
                    kind="charge",
                    note=note,
                    sale_id=sale.id,
                    created_by=actor.id,
                )
            )
        else:
            db.add(
                CustomerBalance(
                    customer_id=data.customer_id,
                    amount=data.balance_total,
                    entry_date=data.business_date,
                    kind="charge",
                    note=note,
                    sale_id=sale.id,
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
            "invoice_no": data.invoice_no,
            "delivery_id": str(data.delivery_id),
            "customer_id": str(data.customer_id),
            "business_date": str(data.business_date),
            "revenue": str(revenue),
            "cash": str(cash_total),
            "upi": str(data.upi_total),
            "online": str(data.online_total),
            "balance": str(data.balance_total),
            "expenses": str(expenses_total),
        },
    )
    return sale


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
            damaged_qty=sl.damaged_qty,
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

    expenses = [
        SaleExpenseOut(item_id=e.item_id, item_name=name, amount=e.amount)
        for e, name in (
            await db.execute(
                select(Expense, ExpenseItem.name)
                .join(ExpenseItem, ExpenseItem.id == Expense.item_id)
                .where(Expense.sale_id == sale.id)
                .order_by(Expense.created_at)
            )
        ).all()
    ]

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
        invoice_no=sale.invoice_no,
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
        denominations=[
            DenominationIn(note_value=d.note_value, note_count=d.note_count)
            for d in (
                await db.scalars(
                    select(CashDenomination)
                    .where(CashDenomination.sale_id == sale.id)
                    .order_by(CashDenomination.note_value.desc())
                )
            ).all()
        ],
        expenses=expenses,
        expenses_total=sum((e.amount for e in expenses), Decimal(0)),
        cancelled_at=sale.cancelled_at,
        cancel_reason=sale.cancel_reason,
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
