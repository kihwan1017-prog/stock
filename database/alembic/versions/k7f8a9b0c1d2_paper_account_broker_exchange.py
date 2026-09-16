"""revision: k7f8a9b0c1d2

paper_account에 broker_code / exchange_code 메타 추가 (STEP8).
기존 행은 NULL 허용 — 백필 후 필요 시 NOT NULL.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "k7f8a9b0c1d2"
down_revision = "j6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "paper_account",
        sa.Column(
            "broker_code",
            sa.String(length=30),
            nullable=True,
        ),
        schema="trading",
    )
    op.add_column(
        "paper_account",
        sa.Column(
            "exchange_code",
            sa.String(length=20),
            nullable=True,
        ),
        schema="trading",
    )


def downgrade() -> None:
    op.drop_column(
        "paper_account",
        "exchange_code",
        schema="trading",
    )
    op.drop_column(
        "paper_account",
        "broker_code",
        schema="trading",
    )
