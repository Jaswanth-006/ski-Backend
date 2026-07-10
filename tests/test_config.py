"""Config helpers (Phase 7-E deploy)."""

from __future__ import annotations

from app.core.config import _normalize_asyncpg_url


def test_neon_url_is_made_asyncpg_safe() -> None:
    raw = (
        "postgresql+asyncpg://u:p@ep-x-pooler.aws.neon.tech/db"
        "?sslmode=require&channel_binding=require"
    )
    out = _normalize_asyncpg_url(raw)
    assert out is not None
    assert "sslmode" not in out  # renamed
    assert "channel_binding" not in out  # dropped
    assert "ssl=require" in out


def test_plain_local_url_is_untouched() -> None:
    raw = "postgresql+asyncpg://ski:ski@localhost:5432/ski"
    assert _normalize_asyncpg_url(raw) == raw


def test_non_asyncpg_and_empty_pass_through() -> None:
    assert _normalize_asyncpg_url(None) is None
    assert _normalize_asyncpg_url("redis://x") == "redis://x"
