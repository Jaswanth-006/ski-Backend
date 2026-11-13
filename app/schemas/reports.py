"""Date-range report schemas (Phase 8-E)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class StockReportRow(BaseModel):
    cylinder_type_id: uuid.UUID
    code: str
    label: str
    ac4: int  # full cylinders received from the plant
    erv: int  # empty cylinders returned to the plant


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


class DepositReportRow(BaseModel):
    kind: str  # vendor | person | bank_account
    recipient: str
    total: Decimal
    count: int
