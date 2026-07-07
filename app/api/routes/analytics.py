"""EOD analytics route (Phase 4-E). Reads from the replica; net profit is owner-only."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_replica_db
from app.db.models import User
from app.schemas.analytics import EodOut
from app.services import analytics as analytics_service

router = APIRouter(tags=["analytics"])


@router.get("/analytics/eod", response_model=EodOut)
async def eod(
    date: dt.date | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_replica_db),
) -> EodOut:
    on_date = date or dt.date.today()
    include_net = current_user.role == "super_admin"
    return await analytics_service.eod(db, on_date, include_net_profit=include_net)
