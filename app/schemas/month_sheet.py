"""Month sheet schemas — per-day rollup for a calendar month."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.day_sheet import Denomination


class MonthSheetDay(BaseModel):
    business_date: dt.date
    cylinders: int  # full cylinders sold (= stock sold)
    empty_returned: int  # empties sent back to the plant (erv) that day
    cash: Decimal  # hand cash collected
    upi: Decimal
    online: Decimal  # paid direct to the company
    total: Decimal  # cash + upi
    expenses: Decimal
    net: Decimal  # total − expenses
    denominations: list[Denomination]  # hand-cash note breakdown, high value first
    is_closed: bool


class MonthSheetTotals(BaseModel):
    cylinders: int
    empty_returned: int
    cash: Decimal
    upi: Decimal
    online: Decimal
    total: Decimal
    expenses: Decimal
    net: Decimal


class MonthSheetOut(BaseModel):
    year: int
    month: int
    days: list[MonthSheetDay]
    totals: MonthSheetTotals
