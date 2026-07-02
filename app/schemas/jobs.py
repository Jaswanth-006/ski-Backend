"""Job schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel


class JobOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    result_url: str | None = None
    error: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class JobEnqueued(BaseModel):
    job_id: uuid.UUID
    status: str
