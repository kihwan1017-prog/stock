"""Autotrading data quality window + incident ledger.

Revision ID: dq1a2b3c4d5e
Revises: ep1a2b3c4d5e
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "dq1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "ep1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "autotrading_data_quality_window",
        sa.Column("window_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("uba_id", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quality_status", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("first_zero_stage", sa.String(40), nullable=True),
        sa.Column("runtime_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("runner_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("worker_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("exit_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("feed_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("scanner_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("watchdog_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("broker_sync_ok", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("slot_invariant_ok", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("data_freshness_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("process_version_id", sa.BigInteger(), nullable=True),
        sa.Column("incident_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "detail_json",
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
        schema="operation",
    )
    op.create_index(
        "ix_at_dq_window_market_uba_started",
        "autotrading_data_quality_window",
        ["market", "uba_id", "started_at"],
        schema="operation",
    )
    op.create_index(
        "ix_at_dq_window_open",
        "autotrading_data_quality_window",
        ["market", "uba_id", "ended_at"],
        schema="operation",
    )

    op.create_table(
        "autotrading_incident_ledger",
        sa.Column("incident_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("uba_id", sa.BigInteger(), nullable=True),
        sa.Column("signature", sa.String(120), nullable=False),
        sa.Column("classification", sa.String(40), nullable=False),
        sa.Column("first_zero_stage", sa.String(40), nullable=True),
        sa.Column("root_cause", sa.String(120), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("self_heal_level", sa.String(10), nullable=True),
        sa.Column(
            "self_heal_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("result", sa.String(40), nullable=True),
        sa.Column("data_quality_impact", sa.String(32), nullable=True),
        sa.Column(
            "recurrence_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("git_fix", sa.String(64), nullable=True),
        sa.Column(
            "evidence_json",
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
        schema="operation",
    )
    op.create_index(
        "ix_at_incident_sig_market",
        "autotrading_incident_ledger",
        ["market", "uba_id", "signature", "started_at"],
        schema="operation",
    )

    # Shadow quarantine — 원본 삭제 금지, promotion 제외 플래그만
    for table in (
        "upbit_entry_signal_shadow",
        "upbit_ma_exit_forward_shadow",
        "upbit_trailing_forward_shadow",
    ):
        op.add_column(
            table,
            sa.Column(
                "data_quality_status",
                sa.String(32),
                nullable=False,
                server_default="UNKNOWN",
            ),
            schema="operation",
        )
        op.add_column(
            table,
            sa.Column(
                "included_in_research_metrics",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            schema="operation",
        )
        op.add_column(
            table,
            sa.Column("quarantine_reason", sa.String(80), nullable=True),
            schema="operation",
        )
        op.add_column(
            table,
            sa.Column("quality_window_id", sa.BigInteger(), nullable=True),
            schema="operation",
        )


def downgrade() -> None:
    for table in (
        "upbit_entry_signal_shadow",
        "upbit_ma_exit_forward_shadow",
        "upbit_trailing_forward_shadow",
    ):
        op.drop_column(table, "quality_window_id", schema="operation")
        op.drop_column(table, "quarantine_reason", schema="operation")
        op.drop_column(table, "included_in_research_metrics", schema="operation")
        op.drop_column(table, "data_quality_status", schema="operation")
    op.drop_index("ix_at_incident_sig_market", table_name="autotrading_incident_ledger", schema="operation")
    op.drop_table("autotrading_incident_ledger", schema="operation")
    op.drop_index("ix_at_dq_window_open", table_name="autotrading_data_quality_window", schema="operation")
    op.drop_index("ix_at_dq_window_market_uba_started", table_name="autotrading_data_quality_window", schema="operation")
    op.drop_table("autotrading_data_quality_window", schema="operation")
