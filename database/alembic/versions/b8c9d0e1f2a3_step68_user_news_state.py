"""STEP68 — user_news_state + news_article_symbol

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_news_article_symbol_published",
        "news_article",
        ["exchange_code", "symbol", "published_at"],
        schema="news",
    )

    op.create_table(
        "news_article_symbol",
        sa.Column(
            "news_article_symbol_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column("market_code", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column(
            "match_type",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'PROVIDER'"),
        ),
        sa.Column(
            "relevance_score",
            sa.Numeric(5, 4),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["news.news_article.article_id"],
            name="fk_news_article_symbol_article",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "article_id",
            "market_code",
            "symbol",
            name="uq_news_article_symbol_link",
        ),
        schema="news",
    )
    op.create_index(
        "ix_news_article_symbol_market_symbol",
        "news_article_symbol",
        ["market_code", "symbol", "article_id"],
        schema="news",
    )

    # 기존 기사 → 심볼 링크 백필
    op.execute(
        """
        INSERT INTO news.news_article_symbol (
            article_id, market_code, symbol, match_type, relevance_score
        )
        SELECT
            article_id,
            exchange_code,
            symbol,
            'PROVIDER',
            1.0
        FROM news.news_article
        ON CONFLICT DO NOTHING
        """
    )

    op.create_table(
        "user_news_state",
        sa.Column(
            "user_news_state_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_bookmarked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
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
            name="fk_user_news_state_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["news.news_article.article_id"],
            name="fk_user_news_state_article",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "article_id",
            name="uq_user_news_state_user_article",
        ),
        schema="news",
    )
    op.create_index(
        "ix_user_news_state_user_read",
        "user_news_state",
        ["user_id", "is_read"],
        schema="news",
    )
    op.create_index(
        "ix_user_news_state_user_bookmarked",
        "user_news_state",
        ["user_id", "is_bookmarked"],
        schema="news",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_news_state_user_bookmarked",
        table_name="user_news_state",
        schema="news",
    )
    op.drop_index(
        "ix_user_news_state_user_read",
        table_name="user_news_state",
        schema="news",
    )
    op.drop_table("user_news_state", schema="news")
    op.drop_index(
        "ix_news_article_symbol_market_symbol",
        table_name="news_article_symbol",
        schema="news",
    )
    op.drop_table("news_article_symbol", schema="news")
    op.drop_index(
        "ix_news_article_symbol_published",
        table_name="news_article",
        schema="news",
    )
