"""Credit (receivables) schemas (Phase E)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class CreditCreate(BaseModel):
    person_name: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0)
    given_date: dt.date
    note: str | None = Field(default=None, max_length=280)


class CreditOut(BaseModel):
    id: uuid.UUID
    person_name: str
    amount: Decimal
    given_date: dt.date
    note: str | None
    is_settled: bool
    settled_date: dt.date | None
    created_at: dt.datetime
