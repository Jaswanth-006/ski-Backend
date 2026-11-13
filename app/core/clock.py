"""Business-day clock. The agency works in India time; the server runs in UTC."""

from __future__ import annotations

import datetime as dt

IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")


def business_today() -> dt.date:
    """Today's date in India — the default business date (not the server's UTC date)."""
    return dt.datetime.now(IST).date()
