"""UBA readiness용 UPBIT AI/Candle/News 컨텍스트 스냅샷.

trading 패키지는 market analysis 문자열/import 금지이므로 여기서 조회한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session


def snapshot_upbit_ai_context(
    session: Session,
    *,
    symbol: str,
) -> dict[str, Any]:
    """Candle/News/Ollama/latest analysis 조회 — Runtime/주문 없음."""

    out: dict[str, Any] = {
        "symbol": symbol.upper(),
        "candle": {"count": None, "ok": False},
        "news": {"count_today": None, "ok": False, "crypto_dedicated": False},
        "ollama_provider": {"enabled": None, "is_default": None},
        "limitations": [],
    }
    try:
        candle_n = session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM market.candle_minute c
                JOIN market.instrument i ON i.instrument_id = c.instrument_id
                WHERE i.exchange_code = 'UPBIT' AND i.symbol = :symbol
                """
            ),
            {"symbol": symbol.upper()},
        ).scalar()
        out["candle"] = {
            "count": int(candle_n or 0),
            "ok": int(candle_n or 0) > 0,
            "sync_via": "POST /api/v1/upbit/minute/sync",
            "timeframes": [1, 3, 5, 15],
        }
    except Exception as exc:  # noqa: BLE001
        out["candle"] = {"error": type(exc).__name__, "ok": False}

    try:
        news_n = session.execute(
            text(
                """
                SELECT COUNT(*) FROM news.news_article
                WHERE UPPER(exchange_code) IN ('UPBIT', 'CRYPTO')
                  AND created_at >= (NOW() AT TIME ZONE 'utc')::date
                """
            )
        ).scalar()
        out["news"] = {
            "count_today": int(news_n or 0),
            "ok": int(news_n or 0) > 0,
            "crypto_dedicated": False,
            "reuse": "WatchlistNewsSyncJob + Naver (watchlist news_enabled)",
            "note": "KRX/DART disclosure is not used for crypto",
        }
        out["limitations"].append(
            "CRYPTO_NEWS_VIA_WATCHLIST_NAVER_ONLY_NO_DEDICATED_CRAWLER"
        )
    except Exception as exc:  # noqa: BLE001
        out["news"] = {
            "error": type(exc).__name__,
            "ok": False,
            "crypto_dedicated": False,
        }
        out["limitations"].append("NEWS_STATUS_UNAVAILABLE")

    try:
        from stock_platform.ai.providers.management_entities import (
            AIProviderConfigurationEntity,
        )

        rows = list(session.scalars(select(AIProviderConfigurationEntity)))
        ollama = next(
            (r for r in rows if str(r.provider_code).lower() == "ollama"),
            None,
        )
        default = next((r for r in rows if r.is_default), None)
        out["ollama_provider"] = {
            "enabled": bool(ollama.enabled) if ollama else False,
            "is_default": bool(ollama.is_default) if ollama else False,
            "model": getattr(ollama, "model", None) if ollama else None,
            "default_provider": (
                getattr(default, "provider_code", None) if default else None
            ),
            "enable_via": (
                "POST /api/v1/admin/ai/provider-configurations/{id}/enable"
            ),
        }
    except Exception as exc:  # noqa: BLE001
        out["ollama_provider"] = {"error": type(exc).__name__}

    try:
        from stock_platform.operation.upbit_ai_analysis_scheduler import (
            upbit_autotrading_ai_analysis_scheduler,
        )

        out["ai_analysis_job"] = upbit_autotrading_ai_analysis_scheduler.status()
    except Exception as exc:  # noqa: BLE001
        out["ai_analysis_job"] = {"error": type(exc).__name__}

    try:
        from stock_platform.common.settings import get_settings

        ttl = float(
            getattr(get_settings(), "autotrading_ai_analysis_ttl_seconds", 900.0)
            or 900.0
        )
        # 테이블명 문자열은 이 모듈(operation)에만 둔다
        row = session.execute(
            text(
                """
                SELECT market_analysis_id, analyzed_at, confidence,
                       provider_code, model, analysis_status,
                       safe_result, trend_classification, volatility_level
                FROM ai.market_analysis
                WHERE exchange_code = 'UPBIT'
                  AND symbol = :symbol
                  AND analysis_status IN (
                    'VALIDATED_ANALYSIS', 'VALIDATED_WITH_WARNINGS'
                  )
                ORDER BY analyzed_at DESC NULLS LAST, market_analysis_id DESC
                LIMIT 1
                """
            ),
            {"symbol": symbol.upper()},
        ).mappings().first()
        if not row:
            out["latest_analysis"] = {
                "status": "AI_ANALYSIS_MISSING",
                "fresh": False,
                "symbol": symbol.upper(),
            }
        else:
            analyzed_at = row.get("analyzed_at")
            age = None
            fresh = False
            if isinstance(analyzed_at, datetime):
                at = analyzed_at
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
                age = max(
                    0.0,
                    (
                        datetime.now(timezone.utc) - at.astimezone(timezone.utc)
                    ).total_seconds(),
                )
                fresh = age <= ttl
            safe = row.get("safe_result") or {}
            if not isinstance(safe, dict):
                safe = {}
            out["latest_analysis"] = {
                "status": "AI_ANALYSIS_FOUND",
                "fresh": fresh,
                "age_seconds": age,
                "symbol": symbol.upper(),
                "market_analysis_id": int(row["market_analysis_id"]),
                "analysis_at": (
                    analyzed_at.isoformat()
                    if isinstance(analyzed_at, datetime)
                    else None
                ),
                "recommendation": safe.get("recommendation"),
                "confidence": row.get("confidence"),
                "risk_level": safe.get("risk_level"),
                "news_sentiment": safe.get("news_sentiment"),
                "provider": row.get("provider_code"),
                "model": row.get("model"),
                "trend": row.get("trend_classification"),
                "reasons": safe.get("reasons"),
                "summary": safe.get("summary"),
            }
    except Exception as exc:  # noqa: BLE001
        out["latest_analysis"] = {
            "status": "LOOKUP_ERROR",
            "error": type(exc).__name__,
        }

    return out
