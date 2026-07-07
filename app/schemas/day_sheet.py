"""Day sheet schemas (Phase 4-A/B)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel


class DaySheetRow(BaseModel):
    delivery_id: uuid.UUID
    delivery_name: str
    cylinders: int
    cash: Decimal
    upi: Decimal
    total: Decimal


class DaySheetTotals(BaseModel):
    cylinders: int
    cash: Decimal
    upi: Decimal
    total: Decimal


class DaySheetOut(BaseModel):
    business_date: dt.date
    is_closed: bool
    closed_at: dt.datetime | None
    rows: list[DaySheetRow]
    totals: DaySheetTotals
