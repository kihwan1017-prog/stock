"""Exit Order Recovery Shadow Lab V1 tables.

Revision ID: eorlabv1a2b3
Revises: wlshlabv1a2b3
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "eorlabv1a2b3"
down_revision: Union[str, Sequence[str], None] = "wlshlabv1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_exit_order_recovery_shadow_observation",
        sa.Column("observation_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("variant", sa.String(8), nullable=False),
        sa.Column("cohort", sa.String(40), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("binding_id", sa.BigInteger(), nullable=True),
        sa.Column("real_order_id", sa.BigInteger(), nullable=False),
        sa.Column("broker_uuid", sa.String(80), nullable=True),
        sa.Column("exit_reason", sa.String(64), nullable=True),
        sa.Column("real_order_type", sa.String(20), nullable=True),
        sa.Column("real_limit_price", sa.Numeric(28, 8), nullable=True),
        sa.Column("real_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
        sa.Column("shadow_trigger_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shadow_trigger_age_seconds", sa.Numeric(18, 3), nullable=True),
        sa.Column("market_price_at_trigger", sa.Numeric(28, 8), nullable=True),
        sa.Column("best_bid_at_trigger", sa.Numeric(28, 8), nullable=True),
        sa.Column("best_ask_at_trigger", sa.Numeric(28, 8), nullable=True),
        sa.Column("remaining_qty_at_trigger", sa.Numeric(28, 8), nullable=True),
        sa.Column(
            "shadow_action",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'NO_ACTION'"),
        ),
        sa.Column("shadow_reference_price", sa.Numeric(28, 8), nullable=True),
        sa.Column("real_terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("real_terminal_state", sa.String(40), nullable=True),
        sa.Column("real_fill_price", sa.Numeric(28, 8), nullable=True),
        sa.Column("real_filled_qty", sa.Numeric(28, 8), nullable=True),
        sa.Column("real_time_to_fill_seconds", sa.Numeric(18, 3), nullable=True),
        sa.Column("shadow_fill_status", sa.String(40), nullable=True),
        sa.Column("shadow_estimated_fill_price", sa.Numeric(28, 8), nullable=True),
        sa.Column("shadow_time_to_fill_seconds", sa.Numeric(18, 3), nullable=True),
        sa.Column("shadow_slippage_bps", sa.Numeric(18, 6), nullable=True),
        sa.Column("shadow_incremental_pnl", sa.Numeric(28, 8), nullable=True),
        sa.Column("shadow_incremental_cost", sa.Numeric(28, 8), nullable=True),
        sa.Column("evidence_quality", sa.String(16), nullable=True),
        sa.Column("mae_while_waiting", sa.Numeric(28, 8), nullable=True),
        sa.Column("mfe_while_waiting", sa.Numeric(28, 8), nullable=True),
        sa.Column(
            "max_adverse_move_while_waiting", sa.Numeric(28, 8), nullable=True
        ),
        sa.Column(
            "research_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "rule_version",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'exit_order_recovery_shadow_v1'"),
        ),
        sa.Column(
            "meta_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
            "user_broker_account_id",
            "variant",
            "real_order_id",
            name="uq_eor_shadow_uba_var_order",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_eor_shadow_uba_var_status",
        "upbit_exit_order_recovery_shadow_observation",
        ["user_broker_account_id", "variant", "status"],
        schema="operation",
    )
    op.create_index(
        "ix_eor_shadow_symbol",
        "upbit_exit_order_recovery_shadow_observation",
        ["symbol"],
        schema="operation",
    )
    op.create_index(
        "ix_eor_shadow_enrolled",
        "upbit_exit_order_recovery_shadow_observation",
        ["enrolled_at"],
        schema="operation",
    )
    op.create_index(
        "ix_eor_shadow_real_order",
        "upbit_exit_order_recovery_shadow_observation",
        ["real_order_id"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_eor_shadow_real_order",
        table_name="upbit_exit_order_recovery_shadow_observation",
        schema="operation",
    )
    op.drop_index(
        "ix_eor_shadow_enrolled",
        table_name="upbit_exit_order_recovery_shadow_observation",
        schema="operation",
    )
    op.drop_index(
        "ix_eor_shadow_symbol",
        table_name="upbit_exit_order_recovery_shadow_observation",
        schema="operation",
    )
    op.drop_index(
        "ix_eor_shadow_uba_var_status",
        table_name="upbit_exit_order_recovery_shadow_observation",
        schema="operation",
    )
    op.drop_table(
        "upbit_exit_order_recovery_shadow_observation", schema="operation"
    )
