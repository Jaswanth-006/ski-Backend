"""Month sheet schemas — per-day rollup for a calendar month."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel


class MonthSheetDay(BaseModel):
    business_date: dt.date
    cylinders: int
    cash: Decimal
    upi: Decimal
    total: Decimal
    expenses: Decimal
    net: Decimal  # total − expenses
    is_closed: bool


class MonthSheetTotals(BaseModel):
    cylinders: int
    cash: Decimal
    upi: Decimal
    total: Decimal
    expenses: Decimal
    net: Decimal


class MonthSheetOut(BaseModel):
    year: int
    month: int
    days: list[MonthSheetDay]
    totals: MonthSheetTotals
