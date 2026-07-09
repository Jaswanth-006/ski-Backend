"""Prometheus metrics (Phase 7-D).

Request rate, latency, and errors are recorded by the request middleware and exposed at
``GET /metrics`` in Prometheus text format for scraping. Path labels use the matched route
template (e.g. ``/v1/sales/{id}``) rather than the raw path, to keep cardinality bounded.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

__all__ = ["REQUESTS", "LATENCY", "render_latest", "CONTENT_TYPE_LATEST"]

REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "path", "status"],
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
)


def render_latest() -> bytes:
    """The current metrics in Prometheus exposition format."""
    return generate_latest()
