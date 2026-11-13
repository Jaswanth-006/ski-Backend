"""Corrections: edit or delete a recorded entry. Every change carries a reason (audited)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.sales import to_paise


class Reason(BaseModel):
    reason: str = Field(min_length=3, max_length=280)

    @field_validator("reason")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("give a short reason")
        return v


# ---- Purchase (stock) entries ----

StockKind = Literal["ac4", "erv", "return", "intake"]


class StockEntryLine(BaseModel):
    cylinder_type_id: uuid.UUID | None = None
    accessory_id: uuid.UUID | None = None
    condition: Literal["full", "empty"] | None = None
    qty: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _one_item(self) -> StockEntryLine:
        if (self.cylinder_type_id is None) == (self.accessory_id is None):
            raise ValueError("give exactly one of cylinder_type_id or accessory_id")
        if self.cylinder_type_id is not None and self.condition is None:
            raise ValueError("a cylinder line needs a condition")
        if self.accessory_id is not None and self.condition is not None:
            raise ValueError("an accessory line has no condition")
        return self


class StockEntryLineOut(StockEntryLine):
    label: str


class StockEntryOut(BaseModel):
    entry_id: uuid.UUID
    kind: StockKind
    business_date: dt.date
    lines: list[StockEntryLineOut]
    created_at: dt.datetime
    created_by_name: str | None


class StockEntryEdit(Reason):
    business_date: dt.date
    lines: list[StockEntryLine] = Field(min_length=1)


# ---- Expenses ----


class ExpenseEdit(Reason):
    business_date: dt.date
    item_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    method: Literal["cash", "digital"]
    note: str | None = Field(default=None, max_length=500)
    delivery_id: uuid.UUID | None = None

    @field_validator("amount")
    @classmethod
    def _paise(cls, v: Decimal) -> Decimal:
        return to_paise(v)


# ---- Deposits (transfers) ----


class TransferEdit(Reason):
    """Date, amount, method and note; to change where money went, delete and record again."""

    business_date: dt.date
    amount: Decimal = Field(gt=0)
    method: str = Field(min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("amount")
    @classmethod
    def _paise(cls, v: Decimal) -> Decimal:
        return to_paise(v)


# ---- Balance entries (delivery boys + customers) ----


class BalanceEntryEdit(Reason):
    entry_date: dt.date
    amount: Decimal = Field(gt=0)
    method: Literal["cash", "upi"] | None = None  # repayments
    note: str | None = Field(default=None, max_length=280)

    @field_validator("amount")
    @classmethod
    def _paise(cls, v: Decimal) -> Decimal:
        return to_paise(v)


class BalanceEntryOut(BaseModel):
    id: uuid.UUID
    party_kind: Literal["delivery", "customer"]
    party_id: uuid.UUID
    party_name: str
    kind: str  # charge | repayment
    amount: Decimal
    entry_date: dt.date
    method: str | None
    note: str | None
    invoice_no: str | None  # set when a sale created it (edit that invoice instead)
    created_at: dt.datetime


# ---- Credits ----


class CreditEdit(Reason):
    person_name: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0)
    given_date: dt.date
    note: str | None = Field(default=None, max_length=280)

    @field_validator("amount")
    @classmethod
    def _paise(cls, v: Decimal) -> Decimal:
        return to_paise(v)
