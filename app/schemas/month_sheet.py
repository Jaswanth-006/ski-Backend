"""Month sheet schemas — each day sheet's final totals, one row per day."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel


class MonthSheetDay(BaseModel):
    business_date: dt.date
    cylinders: int  # full cylinders sold
    empties: int  # empties that came back with the sales
    damaged: int  # came back damaged or were lost ("Return")
    amount: Decimal  # sale value (incl. per-boy other sales)
    upi: Decimal
    cash: Decimal
    online: Decimal  # paid direct to the company
    balance: Decimal  # left unpaid that day (delivery boys + customers)
    is_closed: bool


class MonthSheetTotals(BaseModel):
    cylinders: int
    empties: int
    damaged: int
    amount: Decimal
    upi: Decimal
    cash: Decimal
    online: Decimal
    balance: Decimal


class MonthSheetOut(BaseModel):
    year: int
    month: int
    days: list[MonthSheetDay]
    totals: MonthSheetTotals
