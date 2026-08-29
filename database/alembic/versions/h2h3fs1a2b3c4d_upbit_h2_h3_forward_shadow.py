"""revision: h2h3fs1a2b3c4d
Upbit H2/H3 frozen forward-shadow opportunities (research only).

Revises: uei1a2b3c4d5e
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h2h3fs1a2b3c4d"
down_revision: Union[str, Sequence[str], None] = "uei1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_h2_h3_forward_shadow",
        sa.Column("shadow_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("strategy", sa.String(8), nullable=False),
        sa.Column("rule_hash", sa.String(32), nullable=False),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_reference_price", sa.Numeric(28, 12), nullable=False),
        sa.Column(
            "feature_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "research_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "outcome_status",
            sa.String(40),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "outcome_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "strategy",
            "symbol",
            "evaluated_at",
            "rule_hash",
            name="uq_h2h3_fs_strat_sym_at_hash",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_h2h3_fs_status_eval",
        "upbit_h2_h3_forward_shadow",
        ["outcome_status", "evaluated_at"],
        schema="operation",
    )
    op.create_index(
        "ix_h2h3_fs_strategy_eval",
        "upbit_h2_h3_forward_shadow",
        ["strategy", "evaluated_at"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_h2h3_fs_strategy_eval",
        table_name="upbit_h2_h3_forward_shadow",
        schema="operation",
    )
    op.drop_index(
        "ix_h2h3_fs_status_eval",
        table_name="upbit_h2_h3_forward_shadow",
        schema="operation",
    )
    op.drop_table("upbit_h2_h3_forward_shadow", schema="operation")
