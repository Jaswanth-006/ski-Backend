"""seed data — Indane cylinder types + one super_admin

Idempotent (ON CONFLICT DO NOTHING), so re-running is safe. The admin password is
argon2id-hashed from settings (default must be rotated after first login).

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from argon2 import PasswordHasher

from app.core.config import settings

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Real Indane varieties (DESIGN_SYSTEM §1 / agency catalog).
CYLINDER_TYPES = [
    ("14.2kg", "14.2 kg Domestic"),
    ("5kg", "5 kg Domestic"),
    ("19kg", "19 kg Commercial"),
    ("47.5kg", "47.5 kg Commercial"),
]


def upgrade() -> None:
    bind = op.get_bind()

    for code, label in CYLINDER_TYPES:
        bind.execute(
            sa.text(
                "INSERT INTO cylinder_types (code, label, is_active) "
                "VALUES (:code, :label, TRUE) ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "label": label},
        )

    password_hash = PasswordHasher().hash(settings.seed_admin_password)
    bind.execute(
        sa.text(
            "INSERT INTO users (name, role, phone, password_hash, is_active) "
            "VALUES (:name, 'super_admin', :phone, :password_hash, TRUE) "
            "ON CONFLICT (phone) DO NOTHING"
        ),
        {
            "name": settings.seed_admin_name,
            "phone": settings.seed_admin_phone,
            "password_hash": password_hash,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM users WHERE phone = :phone AND role = 'super_admin'"),
        {"phone": settings.seed_admin_phone},
    )
    bind.execute(
        sa.text("DELETE FROM cylinder_types WHERE code = ANY(:codes)"),
        {"codes": [code for code, _ in CYLINDER_TYPES]},
    )
