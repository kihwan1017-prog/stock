"""Waiting Lifecycle Forward Shadow Lab V1 tables.

Revision ID: wlshlabv1a2b3
Revises: eoslabv2a1b2c3
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "wlshlabv1a2b3"
down_revision: Union[str, Sequence[str], None] = "eoslabv2a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upbit_waiting_lifecycle_shadow_observation",
        sa.Column("observation_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("variant", sa.String(8), nullable=False),
        sa.Column("cohort", sa.String(40), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("selection_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_id", sa.BigInteger(), nullable=True),
        sa.Column("candidate_snapshot_id", sa.String(80), nullable=True),
        sa.Column("strategy_id", sa.BigInteger(), nullable=True),
        sa.Column("deployment_id", sa.BigInteger(), nullable=True),
        sa.Column("slot_id", sa.BigInteger(), nullable=True),
        sa.Column("waiting_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ttl_anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_score", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.String(40),
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
        sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_candidate_id", sa.BigInteger(), nullable=True),
        sa.Column("replacement_selection_id", sa.BigInteger(), nullable=True),
        sa.Column("replacement_score", sa.Float(), nullable=True),
        sa.Column("terminal_stage", sa.String(64), nullable=True),
        sa.Column(
            "real_buy_filled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "shadow_expired_but_real_later_bought",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_decision", sa.String(40), nullable=True),
        sa.Column("last_block_reason", sa.String(80), nullable=True),
        sa.Column(
            "consecutive_no_signal",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "evaluation_count",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
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
            server_default=sa.text("'waiting_lifecycle_shadow_v1'"),
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
            "selection_id",
            "cohort",
            name="uq_wl_shadow_obs_uba_var_sel_cohort",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_wl_shadow_obs_uba_var_status",
        "upbit_waiting_lifecycle_shadow_observation",
        ["user_broker_account_id", "variant", "status"],
        schema="operation",
    )
    op.create_index(
        "ix_wl_shadow_obs_symbol",
        "upbit_waiting_lifecycle_shadow_observation",
        ["symbol"],
        schema="operation",
    )
    op.create_index(
        "ix_wl_shadow_obs_enrolled",
        "upbit_waiting_lifecycle_shadow_observation",
        ["enrolled_at"],
        schema="operation",
    )

    op.create_table(
        "upbit_waiting_lifecycle_shadow_event",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("observation_id", sa.BigInteger(), nullable=True),
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=False),
        sa.Column("variant", sa.String(8), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("age_seconds", sa.Float(), nullable=True),
        sa.Column("decision", sa.String(40), nullable=True),
        sa.Column("block_reason", sa.String(80), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("symbol", sa.String(40), nullable=True),
        sa.Column("selection_id", sa.BigInteger(), nullable=True),
        sa.Column("dedupe_key", sa.String(200), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="operation",
    )
    op.create_index(
        "ix_wl_shadow_evt_obs_type_at",
        "upbit_waiting_lifecycle_shadow_event",
        ["observation_id", "event_type", "observed_at"],
        schema="operation",
    )
    op.create_index(
        "ix_wl_shadow_evt_dedupe",
        "upbit_waiting_lifecycle_shadow_event",
        ["dedupe_key"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wl_shadow_evt_dedupe",
        table_name="upbit_waiting_lifecycle_shadow_event",
        schema="operation",
    )
    op.drop_index(
        "ix_wl_shadow_evt_obs_type_at",
        table_name="upbit_waiting_lifecycle_shadow_event",
        schema="operation",
    )
    op.drop_table("upbit_waiting_lifecycle_shadow_event", schema="operation")
    op.drop_index(
        "ix_wl_shadow_obs_enrolled",
        table_name="upbit_waiting_lifecycle_shadow_observation",
        schema="operation",
    )
    op.drop_index(
        "ix_wl_shadow_obs_symbol",
        table_name="upbit_waiting_lifecycle_shadow_observation",
        schema="operation",
    )
    op.drop_index(
        "ix_wl_shadow_obs_uba_var_status",
        table_name="upbit_waiting_lifecycle_shadow_observation",
        schema="operation",
    )
    op.drop_table(
        "upbit_waiting_lifecycle_shadow_observation", schema="operation"
    )
