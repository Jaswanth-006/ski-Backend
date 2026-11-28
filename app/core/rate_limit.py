"""Login brute-force throttle (Phase 7-B).

Counts consecutive failed logins per phone and blocks once the threshold is reached within
the window. A successful login clears the counter. Counts live in Redis when it is set up;
if Redis is missing or down they are kept in this process instead, so the throttle still
works on a single-instance deploy (it used to switch itself off without Redis).
"""

from __future__ import annotations

import time

from app.core.config import settings
from app.core.redis import get_redis

# phone → (failed count, window ends at monotonic seconds). Used when Redis is unavailable.
_local: dict[str, tuple[int, float]] = {}


def _key(phone: str) -> str:
    return f"login:fail:{phone}"


def _local_count(phone: str) -> int:
    count, until = _local.get(phone, (0, 0.0))
    if until <= time.monotonic():
        _local.pop(phone, None)
        return 0
    return count


def _local_fail(phone: str) -> None:
    count = _local_count(phone)
    until = (
        _local[phone][1] if count else time.monotonic() + settings.login_rate_limit_window_seconds
    )
    _local[phone] = (count + 1, until)
    if len(_local) > 10_000:  # keep memory bounded: drop expired entries
        for p in [p for p, (_, u) in _local.items() if u <= time.monotonic()]:
            _local.pop(p, None)


async def is_login_blocked(phone: str) -> bool:
    try:
        redis = get_redis()
        try:
            value = await redis.get(_key(phone))
        finally:
            await redis.aclose()
    except Exception:
        return _local_count(phone) >= settings.login_rate_limit_max
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
        _local_fail(phone)


async def clear_login_failures(phone: str) -> None:
    _local.pop(phone, None)
    try:
        redis = get_redis()
        try:
            await redis.delete(_key(phone))
        finally:
            await redis.aclose()
    except Exception:
        pass
