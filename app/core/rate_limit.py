"""Login brute-force throttle (Phase 7-B).

Counts consecutive failed logins per phone in Redis and blocks once the threshold is
reached within the window. A successful login clears the counter. Every Redis call is
fail-open: if Redis is unavailable the login flow proceeds unthrottled rather than locking
users out.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.redis import get_redis


def _key(phone: str) -> str:
    return f"login:fail:{phone}"


async def is_login_blocked(phone: str) -> bool:
    try:
        redis = get_redis()
        try:
            value = await redis.get(_key(phone))
        finally:
            await redis.aclose()
    except Exception:
        return False  # fail open
    return value is not None and int(value) >= settings.login_rate_limit_max


async def record_login_failure(phone: str) -> None:
    try:
        redis = get_redis()
        try:
            count = await redis.incr(_key(phone))
            if count == 1:
                await redis.expire(_key(phone), settings.login_rate_limit_window_seconds)
        finally:
            await redis.aclose()
    except Exception:
        pass


async def clear_login_failures(phone: str) -> None:
    try:
        redis = get_redis()
        try:
            await redis.delete(_key(phone))
        finally:
            await redis.aclose()
    except Exception:
        pass
