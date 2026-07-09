"""Prometheus metrics endpoint tests (Phase 7-D)."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import SeededUsers


async def test_metrics_exposition(client: tuple[AsyncClient, SeededUsers]) -> None:
    http, _ = client
    # Generate some traffic, then scrape.
    await http.get("/livez")
    res = await http.get("/metrics")
    assert res.status_code == 200
    body = res.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body
    # The route template is used as the label (bounded cardinality).
    assert "/livez" in body
