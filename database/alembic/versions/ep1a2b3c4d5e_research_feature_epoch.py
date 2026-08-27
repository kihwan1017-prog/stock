"""Research feature epoch table — DDL only.

Revision ID: ep1a2b3c4d5e
Revises: tr1a2b3c4d5e
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ep1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "tr1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_feature_epoch",
        sa.Column("feature_key", sa.String(80), primary_key=True),
        sa.Column("epoch_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="operation",
    )
    # trailing shadow seed — enroll now() fallback 제거용 고정 epoch
    op.execute(
        sa.text(
            """
            INSERT INTO operation.research_feature_epoch
                (feature_key, epoch_at, source, note)
            VALUES (
                'upbit_trailing_forward_shadow',
                TIMESTAMPTZ '2026-08-27 11:12:00+00',
                'feature_commit_5519e85_deploy_utc',
                'bootstrap seed — historical PRE_EXISTING cohorts unchanged'
            )
            ON CONFLICT (feature_key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_table("research_feature_epoch", schema="operation")
