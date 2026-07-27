"""revision: l8a9b0c1d2e3

auth.user 상태·잠금·온보딩 필드 (통합 로그인 STEP1-B/C).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "l8a9b0c1d2e3"
down_revision = "k7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "password_change_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="auth",
    )
    op.add_column(
        "user",
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema="auth",
    )
    op.add_column(
        "user",
        sa.Column(
            "locked_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="auth",
    )
    op.add_column(
        "user",
        sa.Column(
            "last_login_ip",
            sa.String(length=64),
            nullable=True,
        ),
        schema="auth",
    )
    op.add_column(
        "user",
        sa.Column(
            "onboarding_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="auth",
    )
    # 기존 사용자는 온보딩 완료로 백필 (신규만 온보딩)
    op.execute(
        sa.text(
            "UPDATE auth.\"user\" "
            "SET onboarding_completed_at = COALESCE(created_at, NOW()) "
            "WHERE onboarding_completed_at IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("user", "onboarding_completed_at", schema="auth")
    op.drop_column("user", "last_login_ip", schema="auth")
    op.drop_column("user", "locked_until", schema="auth")
    op.drop_column("user", "failed_login_count", schema="auth")
    op.drop_column("user", "password_change_required", schema="auth")
