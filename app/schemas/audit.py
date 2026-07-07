"""Audit log schema (Phase 3-E)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel


class AuditOut(BaseModel):
    id: int
    actor_id: uuid.UUID | None
    actor_name: str | None
    action: str
    entity: str
    entity_id: str | None
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    created_at: dt.datetime
