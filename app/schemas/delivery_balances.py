"""Delivery-boy balance schemas (Phase K)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class DeliveryBalanceCreate(BaseModel):
    delivery_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    entry_date: dt.date
    kind: str  # 'charge' | 'repayment'
    note: str | None = Field(default=None, max_length=280)
    method: Literal["cash", "upi"] | None = None  # repayments only; defaults to cash
    # A UPI repayment can go straight on to a bank account (else it stays in the cashier box).
    upi_account_id: uuid.UUID | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in ("charge", "repayment"):
            raise ValueError("kind must be 'charge' or 'repayment'")
        return v

    @model_validator(mode="after")
    def _method(self) -> DeliveryBalanceCreate:
        if not (self.kind == "repayment" and self.method == "upi"):
            self.upi_account_id = None
        # How money came in only matters for a repayment (it lands in the cashier box).
        self.method = (self.method or "cash") if self.kind == "repayment" else None
        return self


class DeliveryBalanceEntryOut(BaseModel):
    id: uuid.UUID
    delivery_id: uuid.UUID
    amount: Decimal
    entry_date: dt.date
    kind: str
    note: str | None
    method: str | None = None  # repayments: cash | upi
    created_at: dt.datetime


class DeliveryBalanceSummaryOut(BaseModel):
    delivery_id: uuid.UUID
    delivery_name: str
    charged: Decimal  # total the boy has owed
    repaid: Decimal  # total he has paid back
    balance: Decimal  # charged − repaid (what he still owes)
