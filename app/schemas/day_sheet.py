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
    damaged: int  # cylinders that came back damaged or were lost ("Return")
    amount: Decimal  # sale value of the day's cylinders (incl. per-boy other sales)
    loaded: int  # cylinders loaded out to this driver
    returned: int  # cylinders brought back
    cash: Decimal
    upi: Decimal
    online: Decimal  # paid direct to the company (not settled by the boy)
    total: Decimal  # cash + upi handed in
    expense: Decimal  # all of this boy's expenses that day (route + recorded on Expenses)
    net: Decimal  # total − his expenses paid from the box (route ones never reached it)
    balance: Decimal  # left unpaid that day (added to what he owes)
    handed: Decimal  # cash + upi he handed in (= total)
    # Spent on the route out of the sale's collection: amount = cash + upi + online + balance
    # + route_expense.
    route_expense: Decimal = Decimal(0)
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
    damaged: int
    amount: Decimal
    cash: Decimal
    upi: Decimal
    online: Decimal
    total: Decimal
    expense: Decimal  # sum of driver-attributed expenses
    net: Decimal  # sum of row nets
    balance: Decimal  # sum of balance charges recorded today
    handed: Decimal  # sum of cash + upi handed in
    route_expense: Decimal = Decimal(0)


class AgencyExpense(BaseModel):
    """An expense of the agency itself that day (not tied to a delivery boy)."""

    id: uuid.UUID
    item_name: str
    amount: Decimal
    method: str  # 'cash' (out of the cashier box) | 'digital'
    note: str | None


class DaySheetOut(BaseModel):
    business_date: dt.date
    is_closed: bool
    closed_at: dt.datetime | None
    rows: list[DaySheetRow]
    totals: DaySheetTotals
    expenses_total: Decimal
    net: Decimal  # cash + upi collected − expenses paid from the box (not route ones)
    denomination_totals: list[Denomination]  # aggregated across all drivers, high value first
    cashier_opening: Decimal  # cashier box balance carried into this day
    cashier_closing: Decimal  # cashier box balance at end of this day
    stock: StockSummary  # warehouse opening/loaded/sold/returned/closing for the day
    # Agency expenses (no delivery boy); with the boys' expenses they make expenses_total.
    agency_expenses: list[AgencyExpense] = []
    agency_expense_total: Decimal = Decimal(0)
