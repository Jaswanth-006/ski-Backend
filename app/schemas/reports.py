"""Date-range report schemas (Phase 8-E)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class StockReportRow(BaseModel):
    """One cylinder type, full or empty, over the range: closing = A + B − C (+ other).

    Full:  received = ac4 from the plant, issue = sold.
    Empty: received = empties back from customers through sales, issue = erv to the plant.
    """

    cylinder_type_id: uuid.UUID
    code: str
    label: str
    condition: Literal["full", "empty"]
    opening: int  # A: on hand before the start date
    received: int  # B
    issue: int  # C
    other: int  # damaged / lost write-offs and adjustments (signed, usually ≤ 0)
    closing: int  # A + B − C + other: on hand at the end date


class DeliveryReportRow(BaseModel):
    delivery_id: uuid.UUID
    delivery_name: str
    sales: Decimal  # revenue collected (incl. per-boy other sales)
    full_cylinders: int  # full sold
    empty_cylinders: int  # empties collected back


class DeliveryLedgerRow(BaseModel):
    """One line of a delivery boy's statement: a sale, a balance repayment or a manual charge."""

    entry_date: dt.date
    kind: Literal["sale", "repayment", "charge"]
    invoice_no: str | None = None
    note: str | None = None
    qty: int = 0  # full cylinders sold
    empty_qty: int = 0  # empties collected back
    amount: Decimal = Decimal(0)  # sale value, or a manual charge
    cash: Decimal = Decimal(0)
    upi: Decimal = Decimal(0)
    online: Decimal = Decimal(0)  # billed online, paid to the company
    expenses: Decimal = Decimal(0)  # route expenses he paid out of this sale's collection
    repaid: Decimal = Decimal(0)
    balance: Decimal  # left unpaid on this sale (or the manual charge); 0 on repayments


class DeliveryLedgerOut(BaseModel):
    delivery_id: uuid.UUID
    delivery_name: str
    start: dt.date
    end: dt.date
    rows: list[DeliveryLedgerRow]
    total_qty: int
    total_empty_qty: int
    total_amount: Decimal
    total_cash: Decimal
    total_upi: Decimal
    total_online: Decimal
    total_expenses: Decimal
    total_repaid: Decimal
    total_balance: Decimal  # unpaid in the range minus repaid in the range


class ExpenseReportRow(BaseModel):
    item_id: uuid.UUID
    item_name: str
    total: Decimal
    count: int


class ExpenseItemEntry(BaseModel):
    id: uuid.UUID
    business_date: dt.date
    amount: Decimal
    method: str
    note: str | None
    delivery_name: str | None  # the delivery boy it was spent by / for, if any
    invoice_no: str | None  # set when it was a route expense entered with a sale
    entered_by: str | None  # who recorded it
    created_at: dt.datetime


class ExpenseItemLedgerOut(BaseModel):
    """One expense item over a date range: every entry, newest day first."""

    item_id: uuid.UUID
    item_name: str
    start: dt.date
    end: dt.date
    rows: list[ExpenseItemEntry]
    total: Decimal
    count: int


PartyKind = Literal["cashier_box", "bank_account", "vendor", "person"]


class DepositReportRow(BaseModel):
    """One place money moved through in the range: cashier box, bank account, vendor, person."""

    kind: PartyKind
    ref_id: uuid.UUID | None  # None for the cashier box
    name: str  # "Cashier box", "SBI · Current (Main)", vendor / person name
    money_in: Decimal  # deposits into it (to it)
    money_out: Decimal  # deposits out of it (from it)
    count: int


class DepositLedgerRow(BaseModel):
    id: uuid.UUID
    business_date: dt.date
    from_label: str
    to_label: str
    direction: Literal["in", "out"]  # seen from this place
    amount: Decimal
    method: str
    note: str | None
    balance: Decimal | None  # running balance — bank accounts only
    created_at: dt.datetime


class DepositLedgerOut(BaseModel):
    """Every deposit into or out of one place over a date range."""

    kind: PartyKind
    ref_id: uuid.UUID | None
    name: str
    start: dt.date
    end: dt.date
    opening: Decimal | None  # bank accounts: balance before the start date
    rows: list[DepositLedgerRow]
    total_in: Decimal
    total_out: Decimal
    closing: Decimal | None  # bank accounts: opening + in − out
