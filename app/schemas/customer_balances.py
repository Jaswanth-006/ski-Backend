"""Customer balance schemas — what a corporate customer owes, mirroring delivery balances."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class CustomerBalanceCreate(BaseModel):
    customer_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    entry_date: dt.date
    kind: str  # 'charge' | 'repayment'
    note: str | None = Field(default=None, max_length=280)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in ("charge", "repayment"):
            raise ValueError("kind must be 'charge' or 'repayment'")
        return v


class CustomerBalanceEntryOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    amount: Decimal
    entry_date: dt.date
    kind: str
    note: str | None
    created_at: dt.datetime


class CustomerBalanceSummaryOut(BaseModel):
    customer_id: uuid.UUID
    customer_name: str
    charged: Decimal  # total the customer has owed
    repaid: Decimal  # total they have paid back
    balance: Decimal  # charged − repaid (what they still owe)
