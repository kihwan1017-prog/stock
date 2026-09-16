"""STEP70 — user AI recommendation tables

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recommendation_request",
        sa.Column(
            "request_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=True),
        sa.Column("market_code", sa.String(length=20), nullable=False),
        sa.Column(
            "source_type",
            sa.String(length=40),
            nullable=False,
            server_default=sa.text("'WATCHLIST'"),
        ),
        sa.Column(
            "investment_horizon",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'SHORT_TERM'"),
        ),
        sa.Column(
            "risk_level",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'MODERATE'"),
        ),
        sa.Column(
            "recommendation_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("5"),
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'QUEUED'"),
        ),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column(
            "prompt_version",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'v1'"),
        ),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "candidate_symbols_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.user.user_id"],
            name="fk_ai_recommendation_request_user",
            ondelete="CASCADE",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_recommendation_request_user_created",
        "recommendation_request",
        ["user_id", "created_at"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_recommendation_request_user_status",
        "recommendation_request",
        ["user_id", "status"],
        schema="ai",
    )
    op.create_index(
        "ix_ai_recommendation_request_input_hash",
        "recommendation_request",
        ["user_id", "input_hash"],
        schema="ai",
    )

    op.create_table(
        "recommendation_result",
        sa.Column(
            "result_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("market_code", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("symbol_name", sa.String(length=200), nullable=False),
        sa.Column(
            "recommendation_action",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "confidence_score",
            sa.Numeric(5, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_score",
            sa.Numeric(6, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "reasons_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "risk_factors_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "data_snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("data_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["ai.recommendation_request.request_id"],
            name="fk_ai_recommendation_result_request",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "request_id",
            "rank",
            name="uq_ai_recommendation_result_request_rank",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_recommendation_result_symbol",
        "recommendation_result",
        ["market_code", "symbol"],
        schema="ai",
    )

    op.create_table(
        "user_recommendation_state",
        sa.Column(
            "user_recommendation_state_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "is_bookmarked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("feedback_type", sa.String(length=30), nullable=True),
        sa.Column("feedback_comment", sa.String(length=500), nullable=True),
        sa.Column(
            "bookmarked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.user.user_id"],
            name="fk_ai_user_recommendation_state_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["ai.recommendation_request.request_id"],
            name="fk_ai_user_recommendation_state_request",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "request_id",
            name="uq_ai_user_recommendation_state",
        ),
        schema="ai",
    )
    op.create_index(
        "ix_ai_user_recommendation_state_bookmarked",
        "user_recommendation_state",
        ["user_id", "is_bookmarked"],
        schema="ai",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_user_recommendation_state_bookmarked",
        table_name="user_recommendation_state",
        schema="ai",
    )
    op.drop_table("user_recommendation_state", schema="ai")
    op.drop_index(
        "ix_ai_recommendation_result_symbol",
        table_name="recommendation_result",
        schema="ai",
    )
    op.drop_table("recommendation_result", schema="ai")
    op.drop_index(
        "ix_ai_recommendation_request_input_hash",
        table_name="recommendation_request",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_recommendation_request_user_status",
        table_name="recommendation_request",
        schema="ai",
    )
    op.drop_index(
        "ix_ai_recommendation_request_user_created",
        table_name="recommendation_request",
        schema="ai",
    )
    op.drop_table("recommendation_request", schema="ai")
