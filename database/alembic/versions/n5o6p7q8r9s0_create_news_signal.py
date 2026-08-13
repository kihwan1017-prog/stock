"""Alembic: news.news_signal for STEP N5.

Revision ID: n5o6p7q8r9s0
Revises: m4n5o6p7q8r9
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "n5o6p7q8r9s0"
down_revision: Union[str, Sequence[str], None] = "m4n5o6p7q8r9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_signal",
        sa.Column("signal_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column("news_ai_analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("signal_version", sa.String(length=64), nullable=False),
        sa.Column("signal_policy_version", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("strength", sa.String(length=20), nullable=False),
        sa.Column("reliability", sa.String(length=20), nullable=False),
        sa.Column("signal_status", sa.String(length=20), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("news_impact_level", sa.String(length=20), nullable=False),
        sa.Column("time_horizon", sa.String(length=30), nullable=False),
        sa.Column("news_ai_confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("mapping_confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column(
            "risk_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "reason_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signal_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["news.news_article.article_id"],
            name="fk_news_signal_article",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["news_ai_analysis_id"],
            ["news.news_ai_analysis.analysis_id"],
            name="fk_news_signal_analysis",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "news_ai_analysis_id",
            "symbol",
            "signal_version",
            name="uq_news_signal_idempotency",
        ),
        schema="news",
    )
    op.create_index(
        "ix_news_signal_status_created",
        "news_signal",
        ["signal_status", "created_at"],
        schema="news",
    )
    op.create_index(
        "ix_news_signal_symbol_signal_at",
        "news_signal",
        ["symbol", "signal_at"],
        schema="news",
    )


def downgrade() -> None:
    # hard delete 금지 정책 — 테이블 drop만 (데이터 백업은 운영 책임)
    op.drop_index(
        "ix_news_signal_symbol_signal_at",
        table_name="news_signal",
        schema="news",
    )
    op.drop_index(
        "ix_news_signal_status_created",
        table_name="news_signal",
        schema="news",
    )
    op.drop_table("news_signal", schema="news")
