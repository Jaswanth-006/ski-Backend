"""Day sheet consolidation + day close/lock (Phase 4-A/B).

The day sheet aggregates every active delivery person's approved sales for a date.
Closing a day freezes it: the sale transaction rejects posts for a closed date
(see services/sales.py `_assert_day_open`), and the close is audited.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DaySheetStatus, User
from app.schemas.day_sheet import (
    DaySheetOut,
    DaySheetRow,
    DaySheetTotals,
    Denomination,
)
from app.services import audit, cashier_box


class DayAlreadyClosed(Exception):
    """The day is already closed."""


_AGG_SQL = text(
    """
    SELECT s.delivery_id,
           SUM(COALESCE((SELECT SUM(qty) FROM sale_lines WHERE sale_id = s.id), 0)) AS cylinders,
           SUM(COALESCE((SELECT SUM(amount) FROM cash_ledger
                         WHERE sale_id = s.id AND kind = 'cash'), 0))               AS cash,
           SUM(s.upi_total)                                                          AS upi
    FROM sales s
    WHERE s.business_date = :on_date AND s.status = 'approved'
    GROUP BY s.delivery_id
    """
)

_EXP_SQL = text("SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE business_date = :on_date")

_DENOM_SQL = text(
    """
    SELECT s.delivery_id, cd.note_value, SUM(cd.note_count) AS note_count
    FROM cash_denominations cd
    JOIN sales s ON s.id = cd.sale_id
    WHERE s.business_date = :on_date AND s.status = 'approved'
    GROUP BY s.delivery_id, cd.note_value
    HAVING SUM(cd.note_count) > 0
    """
)


async def get_day_sheet(db: AsyncSession, on_date: dt.date) -> DaySheetOut:
    status = await db.get(DaySheetStatus, on_date)

    agg = {
        row["delivery_id"]: row
        for row in (await db.execute(_AGG_SQL, {"on_date": on_date})).mappings().all()
    }
    drivers = (
        (
            await db.execute(
                text(
                    "SELECT id, name FROM users WHERE role = 'delivery' AND is_active = TRUE "
                    "ORDER BY name"
                )
            )
        )
        .mappings()
        .all()
    )

    # Per-driver denomination breakdown: {delivery_id: {note_value: count}}
    denom_by_driver: dict[uuid.UUID, dict[int, int]] = {}
    for row in (await db.execute(_DENOM_SQL, {"on_date": on_date})).mappings().all():
        denom_by_driver.setdefault(row["delivery_id"], {})[int(row["note_value"])] = int(
            row["note_count"]
        )

    rows: list[DaySheetRow] = []
    for d in drivers:
        a = agg.get(d["id"])
        cylinders = int(a["cylinders"]) if a else 0
        cash = Decimal(a["cash"]) if a else Decimal(0)
        upi = Decimal(a["upi"]) if a else Decimal(0)
        notes = denom_by_driver.get(d["id"], {})
        rows.append(
            DaySheetRow(
                delivery_id=d["id"],
                delivery_name=d["name"],
                cylinders=cylinders,
                cash=cash,
                upi=upi,
                total=cash + upi,
                denominations=[
                    Denomination(note_value=v, note_count=notes[v])
                    for v in sorted(notes, reverse=True)
                ],
            )
        )

    # Aggregate every driver's notes into a single per-value total.
    combined: dict[int, int] = {}
    for notes in denom_by_driver.values():
        for value, count in notes.items():
            combined[value] = combined.get(value, 0) + count
    denomination_totals = [
        Denomination(note_value=v, note_count=combined[v]) for v in sorted(combined, reverse=True)
    ]

    totals = DaySheetTotals(
        cylinders=sum(r.cylinders for r in rows),
        cash=sum((r.cash for r in rows), Decimal(0)),
        upi=sum((r.upi for r in rows), Decimal(0)),
        total=sum((r.total for r in rows), Decimal(0)),
    )
    expenses_total = Decimal(await db.scalar(_EXP_SQL, {"on_date": on_date}) or 0)
    cashier_opening, cashier_closing = await cashier_box.opening_closing(db, on_date)
    return DaySheetOut(
        business_date=on_date,
        is_closed=bool(status and status.is_closed),
        closed_at=status.closed_at if status else None,
        rows=rows,
        totals=totals,
        expenses_total=expenses_total,
        net=totals.total - expenses_total,
        denomination_totals=denomination_totals,
        cashier_opening=cashier_opening,
        cashier_closing=cashier_closing,
    )


async def close_day(db: AsyncSession, on_date: dt.date, actor: User) -> DaySheetOut:
    status = await db.get(DaySheetStatus, on_date)
    if status is not None and status.is_closed:
        raise DayAlreadyClosed()

    now = dt.datetime.now(tz=dt.UTC)
    if status is None:
        db.add(
            DaySheetStatus(business_date=on_date, is_closed=True, closed_by=actor.id, closed_at=now)
        )
    else:
        status.is_closed = True
        status.closed_by = actor.id
        status.closed_at = now

    await audit.write(
        db, actor.id, "daysheet.close", "day_sheet", str(on_date), new={"closed_by": actor.name}
    )
    await db.commit()
    return await get_day_sheet(db, on_date)
