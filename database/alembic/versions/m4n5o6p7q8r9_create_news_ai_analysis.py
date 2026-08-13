"""Alembic: news.news_ai_analysis for STEP N4.

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "m4n5o6p7q8r9"
down_revision: Union[str, Sequence[str], None] = "l3m4n5o6p7q8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_ai_analysis",
        sa.Column("analysis_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column("analysis_version", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=True),
        sa.Column("sentiment", sa.String(length=20), nullable=True),
        sa.Column("news_impact_level", sa.String(length=20), nullable=True),
        sa.Column("time_horizon", sa.String(length=30), nullable=True),
        sa.Column("market_scope", sa.String(length=30), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("reasoning_summary", sa.Text(), nullable=True),
        sa.Column("news_ai_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "affected_symbols",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "risk_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "trusted_symbols_input",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "truncated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("elapsed_ms", sa.BigInteger(), nullable=True),
        sa.Column(
            "raw_result",
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
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["news.news_article.article_id"],
            name="fk_news_ai_analysis_article",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "article_id",
            "analysis_version",
            "model_name",
            "prompt_version",
            "input_hash",
            name="uq_news_ai_analysis_idempotency",
        ),
        schema="news",
    )
    op.create_index(
        "ix_news_ai_analysis_status_created",
        "news_ai_analysis",
        ["status", "created_at"],
        schema="news",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_news_ai_analysis_status_created",
        table_name="news_ai_analysis",
        schema="news",
    )
    op.drop_table("news_ai_analysis", schema="news")
