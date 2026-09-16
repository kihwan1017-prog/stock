"""STEP N6 — News matching with look-ahead bias protection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.news.models import NewsArticle
from stock_platform.news.news_signal_models import NewsSignal
from stock_platform.operation.upbit_news_combined_shadow.policy import (
    NEWS_LOOKBACK,
)
from stock_platform.operation.upbit_news_combined_shadow.scoring import (
    signal_contribution,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_influence_eligible(
    *,
    signal: NewsSignal,
    article: NewsArticle | None,
    t0: datetime,
) -> tuple[bool, str]:
    """VALID + published/signal/collected <= T0 + expires > T0 + lookback."""

    t0u = _as_utc(t0)
    if str(signal.signal_status or "") != "VALID":
        return False, f"STATUS_{signal.signal_status}"

    published = signal.published_at
    if published is None:
        return False, "MISSING_PUBLISHED_AT"
    if _as_utc(published) > t0u:
        return False, "FUTURE_PUBLISHED"

    if signal.signal_at is None or _as_utc(signal.signal_at) > t0u:
        return False, "FUTURE_SIGNAL_AT"

    if signal.expires_at is None or _as_utc(signal.expires_at) <= t0u:
        return False, "EXPIRED_AT_T0"

    # collection availability: article.created_at == collected_at proxy
    if article is not None and article.created_at is not None:
        if _as_utc(article.created_at) > t0u:
            return False, "FUTURE_COLLECTED_AT"

    age = t0u - _as_utc(published)
    if age > NEWS_LOOKBACK:
        return False, "LOOKBACK_EXCEEDED"

    return True, "OK"


def load_symbol_signals(
    session: Session,
    *,
    symbol: str,
    t0: datetime,
) -> list[dict[str, Any]]:
    """symbol exact match — influence + provenance용 전체 (VALID/외 포함)."""

    t0u = _as_utc(t0)
    # T0 이후 published만 과도하게 긁지 않도록 lookback window 전후 조회
    window_start = t0u - NEWS_LOOKBACK - NEWS_LOOKBACK  # 여유
    rows = session.execute(
        select(NewsSignal, NewsArticle)
        .outerjoin(
            NewsArticle,
            NewsArticle.article_id == NewsSignal.article_id,
        )
        .where(
            NewsSignal.symbol == symbol.upper(),
            NewsSignal.published_at.is_not(None),
            NewsSignal.published_at >= window_start,
            NewsSignal.published_at <= t0u,
        )
        .order_by(NewsSignal.published_at.desc())
    ).all()

    out: list[dict[str, Any]] = []
    for signal, article in rows:
        ok, reason = is_influence_eligible(
            signal=signal, article=article, t0=t0u
        )
        pub = signal.published_at or t0u
        contrib = signal_contribution(
            direction=str(signal.direction or "UNKNOWN"),
            strength=str(signal.strength or "WEAK"),
            reliability=str(signal.reliability or "LOW"),
            published_at=pub,
            t0=t0u,
            influence_allowed=ok,
        )
        out.append(
            {
                "signal_id": signal.signal_id,
                "article_id": signal.article_id,
                "news_ai_analysis_id": signal.news_ai_analysis_id,
                "symbol": signal.symbol,
                "direction": signal.direction,
                "strength": signal.strength,
                "reliability": signal.reliability,
                "signal_status": signal.signal_status,
                "event_type": signal.event_type,
                "news_impact_level": signal.news_impact_level,
                "time_horizon": signal.time_horizon,
                "published_at": (
                    signal.published_at.isoformat()
                    if signal.published_at
                    else None
                ),
                "signal_at": (
                    signal.signal_at.isoformat() if signal.signal_at else None
                ),
                "expires_at": (
                    signal.expires_at.isoformat()
                    if signal.expires_at
                    else None
                ),
                "collected_at": (
                    article.created_at.isoformat()
                    if article is not None and article.created_at
                    else None
                ),
                "signal_version": signal.signal_version,
                "influence_allowed": ok,
                "exclude_reason": None if ok else reason,
                **contrib,
            }
        )
    return out
