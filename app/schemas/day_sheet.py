"""Day sheet schemas (Phase 4-A/B)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel


class Denomination(BaseModel):
    note_value: int
    note_count: int


class DaySheetRow(BaseModel):
    delivery_id: uuid.UUID
    delivery_name: str
    cylinders: int
    cash: Decimal
    upi: Decimal
    total: Decimal
    denominations: list[Denomination]  # this driver's note breakdown, high value first


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
    expenses_total: Decimal
    net: Decimal  # collection total − expenses
    denomination_totals: list[Denomination]  # aggregated across all drivers, high value first
