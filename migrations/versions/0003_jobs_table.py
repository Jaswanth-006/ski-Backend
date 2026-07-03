"""jobs table (async job tracking)

Deferred from Phase 0-B; added with the async infrastructure in Phase 0-F.
Canonical DDL: 01-BACKEND-PRD §4.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE jobs (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            kind         TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'queued'
                         CHECK (status IN ('queued','running','done','failed')),
            requested_by UUID REFERENCES users(id),
            result_url   TEXT,
            error        TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS jobs")
