"""Cashier box schema (Phase 8-A) — persistent cash-in-hand."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel


class CashierBoxOut(BaseModel):
    business_date: dt.date
    opening: Decimal  # carried from the previous day's closing
    collected: Decimal  # cash + UPI collected on this date
    repaid: Decimal  # balance repayments received on this date (cash + UPI)
    expenses: Decimal  # expenses on this date
    deposited: Decimal  # box-sourced deposits on this date
    closing: Decimal  # opening + collected + repaid − expenses − deposited
    # Physical hand cash only (excludes UPI): cash collected + cash repaid − cash expenses
    # − deposits.
    hand_cash_opening: Decimal
    hand_cash_collected: Decimal
    hand_cash_repaid: Decimal
    hand_cash_closing: Decimal
