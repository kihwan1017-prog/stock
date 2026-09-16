"""AutoTrading process version + execution trace tables.

Revision ID: pv1a2b3c4d5e
Revises: es1a2b3c4d5e
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "pv1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = "es1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "autotrading_process_version",
        sa.Column("process_version_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("broker_code", sa.String(20), nullable=False),
        sa.Column("version_code", sa.String(64), nullable=False),
        sa.Column("version_name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("git_commit", sa.String(40), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("config_snapshot_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("component_snapshot_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evidence_refs_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by", sa.String(64), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("market", "version_code", name="uq_atpv_market_version_code"),
        schema="operation",
    )
    op.create_index("ix_atpv_market_status", "autotrading_process_version", ["market", "status"], schema="operation")

    op.create_table(
        "autotrading_logic_version",
        sa.Column("logic_version_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("component_type", sa.String(40), nullable=False),
        sa.Column("version_code", sa.String(64), nullable=False),
        sa.Column("rule_identifier", sa.String(120), nullable=True),
        sa.Column("rule_version", sa.String(64), nullable=True),
        sa.Column("module_path", sa.String(240), nullable=True),
        sa.Column("git_commit", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("config_snapshot_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("rule_snapshot_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "market", "component_type", "version_code", name="uq_atlv_market_component_version"
        ),
        schema="operation",
    )
    op.create_index(
        "ix_atlv_market_component",
        "autotrading_logic_version",
        ["market", "component_type"],
        schema="operation",
    )

    op.create_table(
        "autotrading_process_component_link",
        sa.Column("link_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("process_version_id", sa.BigInteger(), nullable=False),
        sa.Column("logic_version_id", sa.BigInteger(), nullable=False),
        sa.Column("component_type", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "process_version_id", "component_type", name="uq_atpcl_process_component"
        ),
        schema="operation",
    )

    op.create_table(
        "autotrading_process_change",
        sa.Column("change_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("change_type", sa.String(40), nullable=False),
        sa.Column("component", sa.String(40), nullable=True),
        sa.Column("before_version_code", sa.String(64), nullable=True),
        sa.Column("after_version_code", sa.String(64), nullable=True),
        sa.Column("before_snapshot_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("after_snapshot_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("git_commit", sa.String(40), nullable=True),
        sa.Column("evidence_refs_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("real_policy_changed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("research_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="operation",
    )
    op.create_index(
        "ix_atpc_market_deployed",
        "autotrading_process_change",
        ["market", "deployed_at"],
        schema="operation",
    )

    op.create_table(
        "autotrading_execution_trace",
        sa.Column("trace_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("broker_code", sa.String(20), nullable=False),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("process_version_id", sa.BigInteger(), nullable=True),
        sa.Column("completeness", sa.String(20), nullable=False, server_default="UNKNOWN"),
        sa.Column("outcome", sa.String(40), nullable=True),
        sa.Column("selection_id", sa.BigInteger(), nullable=True),
        sa.Column("slot_id", sa.BigInteger(), nullable=True),
        sa.Column("buy_order_id", sa.BigInteger(), nullable=True),
        sa.Column("sell_order_id", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="operation",
    )
    op.create_index(
        "ix_atet_market_symbol_created",
        "autotrading_execution_trace",
        ["market", "symbol", "created_at"],
        schema="operation",
    )
    op.create_index(
        "ix_atet_process_version",
        "autotrading_execution_trace",
        ["process_version_id"],
        schema="operation",
    )

    op.create_table(
        "autotrading_trace_event",
        sa.Column("trace_event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("trace_id", sa.BigInteger(), nullable=False),
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("process_version_id", sa.BigInteger(), nullable=True),
        sa.Column("logic_version_id", sa.BigInteger(), nullable=True),
        sa.Column("input_snapshot_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_snapshot_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_refs_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "trace_id",
            "stage",
            "event_type",
            "occurred_at",
            name="uq_atte_trace_stage_type_at",
        ),
        schema="operation",
    )
    op.create_index("ix_atte_trace_id", "autotrading_trace_event", ["trace_id"], schema="operation")


def downgrade() -> None:
    op.drop_table("autotrading_trace_event", schema="operation")
    op.drop_table("autotrading_execution_trace", schema="operation")
    op.drop_table("autotrading_process_change", schema="operation")
    op.drop_table("autotrading_process_component_link", schema="operation")
    op.drop_table("autotrading_logic_version", schema="operation")
    op.drop_table("autotrading_process_version", schema="operation")
