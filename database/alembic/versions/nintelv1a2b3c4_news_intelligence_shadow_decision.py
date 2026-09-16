"""Alembic: operation.news_intelligence_shadow_decision

Revision ID: nintelv1a2b3c4
Revises: madcv1lab1a2b3
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "nintelv1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "madcv1lab1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS operation")
    op.create_table(
        "news_intelligence_shadow_decision",
        sa.Column(
            "decision_id", sa.BigInteger(), sa.Identity(), primary_key=True
        ),
        sa.Column("pipeline_version", sa.String(64), nullable=False),
        sa.Column("market_code", sa.String(20), nullable=False),
        sa.Column("source_kind", sa.String(40), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=True),
        sa.Column("event_key", sa.String(160), nullable=False),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.Column("category", sa.String(40), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column(
            "severity",
            sa.String(20),
            nullable=False,
            server_default="INFO",
        ),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "effective_start_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
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
            "market_code",
            "event_key",
            name="uq_news_intel_shadow_market_event",
        ),
        schema="operation",
    )
    op.create_index(
        "ix_news_intel_shadow_market_created",
        "news_intelligence_shadow_decision",
        ["market_code", "created_at"],
        schema="operation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_news_intel_shadow_market_created",
        table_name="news_intelligence_shadow_decision",
        schema="operation",
    )
    op.drop_table("news_intelligence_shadow_decision", schema="operation")
