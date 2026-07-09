"""Request-context middleware: assign/propagate a request id and emit one access log
line per request (with method, path, status, and duration).
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_ctx
from app.core.metrics import LATENCY, REQUESTS

_access_logger = logging.getLogger("app.access")


def _route_label(request: Request) -> str:
    """Matched route template (e.g. /v1/sales/{id}) to keep metric cardinality bounded."""
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = time.perf_counter() - start
            duration_ms = round(elapsed * 1000, 2)
            path = _route_label(request)
            REQUESTS.labels(request.method, path, "500").inc()
            LATENCY.labels(request.method, path).observe(elapsed)
            _access_logger.exception(
                "request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                },
            )
            raise
        else:
            elapsed = time.perf_counter() - start
            duration_ms = round(elapsed * 1000, 2)
            path = _route_label(request)
            REQUESTS.labels(request.method, path, str(response.status_code)).inc()
            LATENCY.labels(request.method, path).observe(elapsed)
            _access_logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            response.headers["X-Request-ID"] = request_id
            # Security headers (Phase 7-B).
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            return response
        finally:
            request_id_ctx.reset(token)
