"""Closed-day lock shared by every entry that lands on a business date.

Once a day sheet is closed, office staff can no longer add or change anything dated that day
(sales, stock, expenses, deposits, balance entries). The owner still can, to fix mistakes.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DaySheetStatus, User


class DayLocked(Exception):
    """The business date's day sheet is closed and the actor is not the owner."""

    def __init__(self, business_date: dt.date) -> None:
        self.business_date = business_date
        super().__init__(f"{business_date} is closed — only the owner can change it")


async def is_closed(db: AsyncSession, business_date: dt.date) -> bool:
    status = await db.get(DaySheetStatus, business_date)
    return status is not None and status.is_closed


async def ensure_open(db: AsyncSession, business_date: dt.date, actor: User) -> None:
    if actor.role != "super_admin" and await is_closed(db, business_date):
        raise DayLocked(business_date)
