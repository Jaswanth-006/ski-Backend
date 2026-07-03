"""Sentry error tracking (01-BACKEND-PRD §15). No-op unless SENTRY_DSN is set.

Sentry's Starlette/FastAPI integration auto-captures unhandled exceptions, so once
initialized here nothing else needs wiring in the request path.
"""

from __future__ import annotations

import logging
from typing import Any

import sentry_sdk

from app.core.config import Settings

logger = logging.getLogger("app.observability")


def init_sentry(settings: Settings, transport: Any | None = None) -> bool:
    """Initialize Sentry if a DSN is configured. Returns True when enabled.

    `transport` is a test seam (pass a capturing transport); production leaves it None.
    """
    if not settings.sentry_dsn:
        logger.info("sentry disabled (no DSN configured)")
        return False

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.version,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        transport=transport,
    )
    logger.info("sentry enabled", extra={"environment": settings.environment})
    return True
