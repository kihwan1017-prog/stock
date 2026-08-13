"""Alembic: operation.upbit_news_combined_shadow for STEP N6.

Revision ID: o6p7q8r9s0t1
Revises: n5o6p7q8r9s0
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "o6p7q8r9s0t1"
down_revision: Union[str, Sequence[str], None] = "n5o6p7q8r9s0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS operation")
    op.create_table(
        "upbit_news_combined_shadow",
        sa.Column(
            "experiment_id", sa.BigInteger(), sa.Identity(), primary_key=True
        ),
        sa.Column("experiment_version", sa.String(64), nullable=False),
        sa.Column("combined_policy_version", sa.String(64), nullable=False),
        sa.Column("scanner_run_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column(
            "candidate_detected_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("control_scanner_rank", sa.Integer(), nullable=True),
        sa.Column("control_scanner_score", sa.Float(), nullable=True),
        sa.Column(
            "control_market_ai_recommendation", sa.String(20), nullable=True
        ),
        sa.Column("control_market_ai_confidence", sa.Float(), nullable=True),
        sa.Column("control_market_ai_risk", sa.String(20), nullable=True),
        sa.Column("control_analysis_id", sa.BigInteger(), nullable=True),
        sa.Column("control_shadow_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "technical_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("news_context_status", sa.String(32), nullable=False),
        sa.Column(
            "eligible_news_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "news_signal_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "news_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "experimental_news_component",
            sa.Float(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "news_component_normalized",
            sa.Float(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "experimental_combined_score",
            sa.Float(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("experimental_decision", sa.String(20), nullable=False),
        sa.Column("counterfactual_rank", sa.Integer(), nullable=True),
        sa.Column("rank_delta", sa.Integer(), nullable=True),
        sa.Column("entry_price", sa.Numeric(28, 12), nullable=False),
        sa.Column("evaluation_status", sa.String(20), nullable=False),
        sa.Column("return_5m_pct", sa.Float(), nullable=True),
        sa.Column("return_15m_pct", sa.Float(), nullable=True),
        sa.Column("return_30m_pct", sa.Float(), nullable=True),
        sa.Column("return_60m_pct", sa.Float(), nullable=True),
        sa.Column("mfe_pct", sa.Float(), nullable=True),
        sa.Column("mae_pct", sa.Float(), nullable=True),
        sa.Column(
            "evaluation_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "scanner_run_id",
            "symbol",
            "experiment_version",
            name="uq_news_combined_shadow_idempotency",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_news_combined_shadow_status_created",
        "upbit_news_combined_shadow",
        ["evaluation_status", "created_at"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_news_combined_shadow_status_created",
        table_name="upbit_news_combined_shadow",
        schema="operation",
    )
    op.drop_table("upbit_news_combined_shadow", schema="operation")
