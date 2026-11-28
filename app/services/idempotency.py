"""Repeat-safe saves: an entry posted twice with the same Idempotency-Key is saved once.

The web app sends a fresh key per entry and the same key on a retry (a slow server, a
double-click). The first request claims the key, saves, and stores its response; a repeat
gets that stored response back instead of a second row. Requests without a key behave as
before.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_CLAIM = text(
    "INSERT INTO idempotency_keys (key, scope) VALUES (:k, :s) "
    "ON CONFLICT (key) DO NOTHING RETURNING key"
)
_GET = text("SELECT scope, response FROM idempotency_keys WHERE key = :k")
_SAVE = text("UPDATE idempotency_keys SET response = CAST(:r AS jsonb) WHERE key = :k")
_RELEASE = text("DELETE FROM idempotency_keys WHERE key = :k")
_PRUNE = text("DELETE FROM idempotency_keys WHERE created_at < now() - interval '7 days'")


class KeyConflict(Exception):
    """The key is in use by a different request, or its first request is still saving."""


async def run_once(
    db: AsyncSession,
    key: uuid.UUID | None,
    scope: str,
    save: Callable[[], Awaitable[Any]],
) -> Any:
    """Run ``save`` once per key; a repeat returns the first response (as JSON data)."""
    if key is None:
        return await save()
    await db.execute(_PRUNE)
    claimed = await db.scalar(_CLAIM, {"k": key, "s": scope})
    await db.commit()
    if claimed is None:
        row = (await db.execute(_GET, {"k": key})).first()
        if row is None or row.scope != scope:
            raise KeyConflict("this Idempotency-Key was already used for a different entry")
        if row.response is None:
            raise KeyConflict("this entry is still being saved — refresh in a moment")
        return row.response
    try:
        result = await save()
    except BaseException:
        # Nothing was saved: free the key so the same entry can be tried again.
        await db.rollback()
        await db.execute(_RELEASE, {"k": key})
        await db.commit()
        raise
    await db.execute(_SAVE, {"k": key, "r": json.dumps(jsonable_encoder(result))})
    await db.commit()
    return result
