"""Redis client factory (Phase 0-F).

Provisioned for cache, login rate-limiting, and WebSocket pub/sub (used by later phases).
Also serves as the Celery broker/result backend (see app/workers/celery_app.py).
"""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from app.core.config import settings


def get_redis() -> Redis:
    client: Redis = from_url(  # type: ignore[no-untyped-call]
        settings.redis_url, encoding="utf-8", decode_responses=True
    )
    return client
