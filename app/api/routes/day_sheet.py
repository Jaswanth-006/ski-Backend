"""Day sheet routes (Phase 4-A/B)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_roles
from app.db.models import User
from app.schemas.day_sheet import DaySheetOut
from app.schemas.jobs import JobEnqueued
from app.services import day_sheet as day_sheet_service
from app.services import jobs as jobs_service
from app.workers.exports import build_day_sheet_xlsx
from app.workers.tasks import export_day_sheet as export_task

router = APIRouter(tags=["day-sheet"])

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/day-sheet/{on_date}", response_model=DaySheetOut)
async def get_day_sheet(
    on_date: dt.date,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> DaySheetOut:
    return await day_sheet_service.get_day_sheet(db, on_date)


@router.post("/day-sheet/{on_date}/close", response_model=DaySheetOut)
async def close_day(
    on_date: dt.date,
    current_user: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> DaySheetOut:
    try:
        return await day_sheet_service.close_day(db, on_date, current_user)
    except day_sheet_service.DayAlreadyClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="the day is already closed") from exc


@router.post(
    "/day-sheet/{on_date}/export", response_model=JobEnqueued, status_code=status.HTTP_202_ACCEPTED
)
async def export_day_sheet(
    on_date: dt.date,
    current_user: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> JobEnqueued:
    """Kick off an async Excel export; poll GET /v1/jobs/{id} for the download URL."""
    job = await jobs_service.create_job(db, kind="export", requested_by=current_user.id)
    export_task.delay(str(job.id), on_date.isoformat())
    return JobEnqueued(job_id=job.id, status=job.status)


@router.get("/day-sheet/{on_date}/export.xlsx", include_in_schema=False)
async def download_day_sheet_xlsx(
    on_date: dt.date,
    _: User = Depends(require_roles("super_admin", "office_admin")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Build and stream the day sheet as an .xlsx directly — no worker/object storage needed."""
    sheet = await day_sheet_service.get_day_sheet(db, on_date)
    return Response(
        content=build_day_sheet_xlsx(sheet),
        media_type=_XLSX,
        headers={"Content-Disposition": f'attachment; filename="day-sheet-{on_date}.xlsx"'},
    )
