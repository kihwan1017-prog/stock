from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stock_platform.database.base import Base


class NewsArticle(Base):
    __tablename__ = "news_article"
    __table_args__ = (
        UniqueConstraint(
            "content_hash",
            name="uq_news_article_content_hash",
        ),
        Index(
            "ix_news_article_symbol_published",
            "exchange_code",
            "symbol",
            "published_at",
        ),
        {"schema": "news"},
    )

    article_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    query_text: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    naver_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    source_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'NAVER'"),
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class NewsArticleSymbol(Base):
    """기사–종목 다대다 연결 (동일 content_hash 재수집 시 종목 추가)."""

    __tablename__ = "news_article_symbol"
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "market_code",
            "symbol",
            name="uq_news_article_symbol_link",
        ),
        Index(
            "ix_news_article_symbol_market_symbol",
            "market_code",
            "symbol",
            "article_id",
        ),
        {"schema": "news"},
    )

    news_article_symbol_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "news.news_article.article_id",
            ondelete="CASCADE",
            name="fk_news_article_symbol_article",
        ),
        nullable=False,
    )
    market_code: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    match_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'PROVIDER'"),
    )
    relevance_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        server_default=text("1.0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class UserNewsState(Base):
    """사용자별 뉴스 읽음·북마크 상태."""

    __tablename__ = "user_news_state"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "article_id",
            name="uq_user_news_state_user_article",
        ),
        Index(
            "ix_user_news_state_user_read",
            "user_id",
            "is_read",
        ),
        Index(
            "ix_user_news_state_user_bookmarked",
            "user_id",
            "is_bookmarked",
        ),
        {"schema": "news"},
    )

    user_news_state_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "auth.user.user_id",
            ondelete="CASCADE",
            name="fk_user_news_state_user",
        ),
        nullable=False,
    )
    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "news.news_article.article_id",
            ondelete="CASCADE",
            name="fk_user_news_state_article",
        ),
        nullable=False,
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    is_bookmarked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    bookmarked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    hidden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class NewsSummary(Base):
    __tablename__ = "news_summary"
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "model_name",
            name="uq_news_summary_article_model",
        ),
        {"schema": "news"},
    )

    summary_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "news.news_article.article_id",
            ondelete="CASCADE",
            name="fk_news_summary_article",
        ),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    importance_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    risks: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class NewsCollectionFailure(Base):
    """뉴스 수집 실패 이력."""

    __tablename__ = "collection_failure"
    __table_args__ = (
        Index(
            "ix_collection_failure_symbol_failed",
            "exchange_code",
            "symbol",
            "failed_at",
        ),
        {"schema": "news"},
    )

    failure_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    exchange_code: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    query_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'NAVER'"),
    )
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    extra_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
