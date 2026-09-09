"""Alembic: Upbit strategy observability V1 tables

Revision ID: uobs1v1a2b3c4
Revises: arecv1orc2a3b4
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "uobs1v1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "arecv1orc2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS operation")

    op.create_table(
        "upbit_strategy_obs_scanner_universe",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("scanner_run_id", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("candidate_rank", sa.BigInteger(), nullable=True),
        sa.Column("candidate_score", sa.Numeric(24, 8), nullable=True),
        sa.Column(
            "selected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "rejected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("reject_reason", sa.String(120), nullable=True),
        sa.Column("scanner_source", sa.String(40), nullable=True),
        sa.Column("price", sa.Numeric(24, 8), nullable=True),
        sa.Column(
            "metrics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "rule_version",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'UPBIT_STRATEGY_OBS_V1'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "scanner_run_id",
            "symbol",
            name="uq_upbit_obs_scanner_run_symbol",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_upbit_obs_scanner_run_selected",
        "upbit_strategy_obs_scanner_universe",
        ["scanner_run_id", "selected"],
        schema="operation",
    )
    op.create_index(
        "ix_upbit_obs_scanner_created",
        "upbit_strategy_obs_scanner_universe",
        ["created_at"],
        schema="operation",
    )

    op.create_table(
        "upbit_strategy_obs_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=True),
        sa.Column("scanner_run_id", sa.String(64), nullable=True),
        sa.Column("selection_id", sa.BigInteger(), nullable=True),
        sa.Column("signal_id", sa.String(120), nullable=True),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("binding_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "rule_version",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'UPBIT_STRATEGY_OBS_V1'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="operation",
    )
    op.create_index(
        "ix_upbit_obs_event_uba_type_created",
        "upbit_strategy_obs_event",
        ["user_broker_account_id", "event_type", "created_at"],
        schema="operation",
    )
    op.create_index(
        "ix_upbit_obs_event_symbol_created",
        "upbit_strategy_obs_event",
        ["symbol", "created_at"],
        schema="operation",
    )
    op.create_index(
        "ix_upbit_obs_event_signal_id",
        "upbit_strategy_obs_event",
        ["signal_id"],
        schema="operation",
    )

    op.create_table(
        "upbit_strategy_obs_order_timeline",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("side_code", sa.String(8), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("binding_id", sa.BigInteger(), nullable=True),
        sa.Column("signal_id", sa.String(120), nullable=True),
        sa.Column("selection_id", sa.BigInteger(), nullable=True),
        sa.Column("candidate_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admission_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("intent_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("broker_submit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("broker_ack_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fill_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "latency_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "note_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "rule_version",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'UPBIT_STRATEGY_OBS_V1'"),
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
            "order_id",
            "side_code",
            name="uq_upbit_obs_order_timeline_order_side",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_upbit_obs_timeline_uba_created",
        "upbit_strategy_obs_order_timeline",
        ["user_broker_account_id", "created_at"],
        schema="operation",
    )

    op.create_table(
        "upbit_strategy_obs_post_trade",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("binding_id", sa.BigInteger(), nullable=False),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("exit_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("mfe_pct", sa.Numeric(18, 8), nullable=True),
        sa.Column("mae_pct", sa.Numeric(18, 8), nullable=True),
        sa.Column("time_to_mfe_seconds", sa.BigInteger(), nullable=True),
        sa.Column("time_to_mae_seconds", sa.BigInteger(), nullable=True),
        sa.Column(
            "post_exit_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "analytics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
            server_default=sa.text("'UPBIT_STRATEGY_OBS_V1'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint("binding_id", name="uq_upbit_obs_post_trade_binding"),
        schema="operation",
    )
    op.create_index(
        "ix_upbit_obs_post_trade_uba_closed",
        "upbit_strategy_obs_post_trade",
        ["user_broker_account_id", "closed_at"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_upbit_obs_post_trade_uba_closed",
        table_name="upbit_strategy_obs_post_trade",
        schema="operation",
    )
    op.drop_table("upbit_strategy_obs_post_trade", schema="operation")
    op.drop_index(
        "ix_upbit_obs_timeline_uba_created",
        table_name="upbit_strategy_obs_order_timeline",
        schema="operation",
    )
    op.drop_table("upbit_strategy_obs_order_timeline", schema="operation")
    op.drop_index(
        "ix_upbit_obs_event_signal_id",
        table_name="upbit_strategy_obs_event",
        schema="operation",
    )
    op.drop_index(
        "ix_upbit_obs_event_symbol_created",
        table_name="upbit_strategy_obs_event",
        schema="operation",
    )
    op.drop_index(
        "ix_upbit_obs_event_uba_type_created",
        table_name="upbit_strategy_obs_event",
        schema="operation",
    )
    op.drop_table("upbit_strategy_obs_event", schema="operation")
    op.drop_index(
        "ix_upbit_obs_scanner_created",
        table_name="upbit_strategy_obs_scanner_universe",
        schema="operation",
    )
    op.drop_index(
        "ix_upbit_obs_scanner_run_selected",
        table_name="upbit_strategy_obs_scanner_universe",
        schema="operation",
    )
    op.drop_table("upbit_strategy_obs_scanner_universe", schema="operation")
