"""Master-data catalog schemas — cylinder varieties (Phase 1-C)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class CylinderTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=120)


class CylinderTypeUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class CylinderTypeOut(BaseModel):
    id: uuid.UUID
    code: str
    label: str
    is_active: bool
