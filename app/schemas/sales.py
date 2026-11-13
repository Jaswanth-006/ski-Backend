"""Sales schemas (Phase 3)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field, field_validator, model_validator


class SaleLineIn(BaseModel):
    cylinder_type_id: uuid.UUID
    qty: int = Field(ge=1)
    empty_qty: int | None = Field(default=None, ge=0)  # empties returned; defaults to qty
    damaged_qty: int = Field(default=0, ge=0)  # came back damaged or lost (not added to stock)


def to_paise(v: Decimal) -> Decimal:
    """Money arrives as JSON numbers (binary floats); keep it to whole paise."""
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class SaleExpenseIn(BaseModel):
    """A route expense the delivery boy paid out of this sale's collection (e.g. fuel)."""

    item_id: uuid.UUID
    amount: Decimal = Field(gt=0)

    @field_validator("amount")
    @classmethod
    def _paise(cls, v: Decimal) -> Decimal:
        return to_paise(v)


class SaleExpenseOut(BaseModel):
    item_id: uuid.UUID
    item_name: str
    amount: Decimal


class DenominationIn(BaseModel):
    note_value: int = Field(gt=0)
    note_count: int = Field(ge=0)


class SaleCreate(BaseModel):
    invoice_no: str = Field(min_length=1, max_length=50)  # unique across sales
    delivery_id: uuid.UUID | None = None  # a delivery boy…
    customer_id: uuid.UUID | None = None  # …or a corporate customer (exactly one)
    business_date: dt.date
    lines: list[SaleLineIn] = Field(min_length=1)
    denominations: list[DenominationIn] = Field(default_factory=list)
    upi_total: Decimal = Field(ge=0, default=Decimal(0))
    online_total: Decimal = Field(ge=0, default=Decimal(0))  # paid direct to the company
    balance_total: Decimal = Field(ge=0, default=Decimal(0))  # uncollected — the party owes it
    # Delivery sales only: spent on the route from this collection; settles part of the sale.
    expenses: list[SaleExpenseIn] = Field(default_factory=list)

    @field_validator("upi_total", "online_total", "balance_total")
    @classmethod
    def _paise(cls, v: Decimal) -> Decimal:
        return to_paise(v)

    @field_validator("invoice_no")
    @classmethod
    def _strip_invoice(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("invoice number is required")
        return v

    @model_validator(mode="after")
    def _one_party(self) -> SaleCreate:
        if (self.delivery_id is None) == (self.customer_id is None):
            raise ValueError("provide exactly one of delivery_id or customer_id")
        if self.expenses and self.delivery_id is None:
            raise ValueError("route expenses only apply to a delivery boy's sale")
        return self


class SaleLineOut(BaseModel):
    cylinder_type_id: uuid.UUID
    code: str
    label: str
    qty: int
    empty_qty: int  # empties returned for this line
    damaged_qty: int  # came back damaged or lost
    unit_price: Decimal  # base cylinder price
    other_sales_per_unit: Decimal  # per-boy extra on top
    line_total: Decimal  # (unit_price + other_sales_per_unit) × qty


class SaleOut(BaseModel):
    id: uuid.UUID
    invoice_no: str | None  # None only for sales recorded before invoice numbers
    delivery_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    party_kind: str  # 'delivery' | 'customer'
    party_name: str
    business_date: dt.date
    status: str
    submitted_via: str
    created_at: dt.datetime
    lines: list[SaleLineOut]
    cash_total: Decimal
    upi_total: Decimal
    online_total: Decimal
    balance_total: Decimal  # uncollected — added to the boy's or customer's balance
    revenue_total: Decimal
    settled_total: Decimal  # cash + upi handed in
    expenses: list[SaleExpenseOut] = Field(default_factory=list)  # route expenses settled here
    expenses_total: Decimal = Decimal(0)
    denominations: list[DenominationIn] = Field(default_factory=list)  # cash notes counted
    cancelled_at: dt.datetime | None = None
    cancel_reason: str | None = None


class SaleCancel(BaseModel):
    reason: str = Field(min_length=3, max_length=280)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("give a short reason")
        return v


class SaleEdit(SaleCancel):
    """Edit = the corrected sale plus why the original was wrong."""

    sale: SaleCreate
