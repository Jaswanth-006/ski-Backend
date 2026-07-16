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
    delivery_id: uuid.UUID  # party id (delivery boy or customer)
    delivery_name: str  # party name
    party_kind: str  # 'delivery' | 'customer'
    cylinders: int  # full cylinders sold
    empties: int  # empty cylinders returned
    loaded: int  # cylinders loaded out to this driver
    returned: int  # cylinders brought back
    cash: Decimal
    upi: Decimal
    online: Decimal  # paid direct to the company (not settled by the boy)
    total: Decimal  # cash + upi collected
    expense: Decimal  # this boy's route expenses for the day
    net: Decimal  # due to office = total - expense
    balance: Decimal  # of `net`, the part he didn't hand in today (added to what he owes)
    handed: Decimal  # what he actually handed in = net - balance
    denominations: list[Denomination]  # this driver's note breakdown, high value first


class StockSummary(BaseModel):
    opening: int  # warehouse cylinders carried into the day
    loaded: int  # total loaded out to drivers
    sold: int  # total sold
    returned: int  # total returned to the warehouse
    closing: int  # warehouse cylinders at end of day


class DaySheetTotals(BaseModel):
    cylinders: int
    empties: int
    cash: Decimal
    upi: Decimal
    online: Decimal
    total: Decimal
    expense: Decimal  # sum of driver-attributed expenses
    net: Decimal  # total - expense
    balance: Decimal  # sum of balance charges recorded today
    handed: Decimal  # net - balance


class DaySheetOut(BaseModel):
    business_date: dt.date
    is_closed: bool
    closed_at: dt.datetime | None
    rows: list[DaySheetRow]
    totals: DaySheetTotals
    expenses_total: Decimal
    net: Decimal  # collection total − expenses
    denomination_totals: list[Denomination]  # aggregated across all drivers, high value first
    cashier_opening: Decimal  # cashier box balance carried into this day
    cashier_closing: Decimal  # cashier box balance at end of this day
    stock: StockSummary  # warehouse opening/loaded/sold/returned/closing for the day
