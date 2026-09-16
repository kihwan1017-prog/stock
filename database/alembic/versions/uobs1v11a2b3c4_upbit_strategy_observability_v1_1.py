"""Alembic: Upbit strategy observability V1.1 counterfactual + run meta

Revision ID: uobs1v11a2b3c4
Revises: uobs1v1a2b3c4

Observation-only. No trading-path coupling.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "uobs1v11a2b3c4"
down_revision: Union[str, Sequence[str], None] = "uobs1v1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS operation")

    op.create_table(
        "upbit_strategy_obs_scanner_run_meta",
        sa.Column("scanner_run_id", sa.String(64), primary_key=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        sa.Column("expected_universe_count", sa.BigInteger(), nullable=False),
        sa.Column("persisted_universe_count", sa.BigInteger(), nullable=False),
        sa.Column(
            "universe_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "meta_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "rule_version",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'UPBIT_STRATEGY_OBS_V1_1'"),
        ),
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
    op.create_index(
        "ix_upbit_obs_run_meta_observed",
        "upbit_strategy_obs_scanner_run_meta",
        ["observed_at"],
        schema="operation",
    )

    op.create_table(
        "upbit_strategy_obs_counterfactual",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("scanner_run_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("horizon_m", sa.BigInteger(), nullable=False),
        sa.Column("forward_return_pct", sa.Numeric(18, 8), nullable=True),
        sa.Column("base_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("forward_price", sa.Numeric(24, 8), nullable=True),
        sa.Column(
            "status",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'PENDING_FUTURE_DATA'"),
        ),
        sa.Column("status_reason", sa.String(120), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "lookahead_forbidden_for_trading",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "rule_version",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'UPBIT_STRATEGY_OBS_V1_1'"),
        ),
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
            "scanner_run_id",
            "symbol",
            "horizon_m",
            name="uq_upbit_obs_cf_run_sym_horizon",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_upbit_obs_cf_status_observed",
        "upbit_strategy_obs_counterfactual",
        ["status", "observed_at"],
        schema="operation",
    )
    op.create_index(
        "ix_upbit_obs_cf_run_selected",
        "upbit_strategy_obs_counterfactual",
        ["scanner_run_id", "selected"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_upbit_obs_cf_run_selected",
        table_name="upbit_strategy_obs_counterfactual",
        schema="operation",
    )
    op.drop_index(
        "ix_upbit_obs_cf_status_observed",
        table_name="upbit_strategy_obs_counterfactual",
        schema="operation",
    )
    op.drop_table("upbit_strategy_obs_counterfactual", schema="operation")
    op.drop_index(
        "ix_upbit_obs_run_meta_observed",
        table_name="upbit_strategy_obs_scanner_run_meta",
        schema="operation",
    )
    op.drop_table("upbit_strategy_obs_scanner_run_meta", schema="operation")
