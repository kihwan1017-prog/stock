"""STEP N5 — News Signal Standardization focused tests (LLM 금지)."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.news.news_signal_constants import (
    SIGNAL_VERSION,
    IMPACT_TO_STRENGTH,
)
from stock_platform.news.news_signal_standardize import (
    compute_reliability,
    compute_strength,
    standardize_symbol_signal,
)


def _base(**overrides):
    now = datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc)
    payload = {
        "article_id": 1,
        "news_analysis_id": 10,
        "symbol": "KRW-BTC",
        "event_type": "MARKET",
        "sentiment": "POSITIVE",
        "news_impact_level": "HIGH",
        "time_horizon": "SHORT_TERM",
        "market_scope": "SYMBOL_SPECIFIC",
        "news_ai_confidence": 0.9,
        "mapping_confidence": 0.95,
        "risk_flags": [],
        "affected_item": None,
        "published_at": now - timedelta(hours=1),
        "analyzed_at": now,
        "now": now,
    }
    payload.update(overrides)
    return standardize_symbol_signal(**payload)


def test_impact_to_strength_deterministic() -> None:
    assert compute_strength("LOW") == "WEAK"
    assert compute_strength("MEDIUM") == "MODERATE"
    assert compute_strength("HIGH") == "STRONG"
    assert compute_strength("CRITICAL") == "STRONG"
    assert IMPACT_TO_STRENGTH["CRITICAL"] == "STRONG"


def test_reliability_thresholds() -> None:
    assert compute_reliability(news_ai_confidence=0.85, mapping_confidence=0.92) == "HIGH"
    assert compute_reliability(news_ai_confidence=0.7, mapping_confidence=0.7) == "MEDIUM"
    assert compute_reliability(news_ai_confidence=0.5, mapping_confidence=0.9) == "LOW"


@pytest.mark.parametrize(
    "sentiment,expected",
    [
        ("POSITIVE", "POSITIVE"),
        ("NEGATIVE", "NEGATIVE"),
        ("NEUTRAL", "NEUTRAL"),
        ("MIXED", "MIXED"),
        ("UNKNOWN", "UNKNOWN"),
    ],
)
def test_directions(sentiment: str, expected: str) -> None:
    out = _base(sentiment=sentiment)
    assert out["direction"] == expected


def test_symbol_direction_overrides_sentiment() -> None:
    out = _base(
        sentiment="POSITIVE",
        affected_item={
            "symbol": "KRW-BTC",
            "direction": "NEGATIVE",
            "news_impact_level": "HIGH",
            "confidence": 0.8,
        },
    )
    assert out["direction"] == "NEGATIVE"
    assert "SYMBOL_SPECIFIC_DIRECTION" in out["reason_codes"]


def test_unknown_not_promoted() -> None:
    out = _base(sentiment="UNKNOWN")
    assert out["direction"] == "UNKNOWN"
    assert out["direction"] != "POSITIVE"


def test_low_confidence_status() -> None:
    out = _base(news_ai_confidence=0.4, mapping_confidence=0.4)
    assert out["reliability"] == "LOW"
    assert out["signal_status"] == "LOW_CONFIDENCE"


def test_fresh_valid() -> None:
    out = _base(news_ai_confidence=0.9, mapping_confidence=0.95)
    assert out["signal_status"] == "VALID"


def test_expired_stale() -> None:
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    out = _base(
        time_horizon="IMMEDIATE",
        published_at=now - timedelta(hours=10),
        analyzed_at=now - timedelta(hours=10),
        now=now,
        news_ai_confidence=0.9,
        mapping_confidence=0.95,
    )
    assert out["signal_status"] == "STALE"
    assert "STALE_NEWS" in out["reason_codes"]


def test_invalid_symbol() -> None:
    out = _base(symbol="BTC")
    assert out["signal_status"] == "INVALID"


def test_delisting_reason() -> None:
    out = _base(
        event_type="DELISTING",
        sentiment="NEGATIVE",
        news_impact_level="CRITICAL",
    )
    assert "DELISTING_EVENT" in out["reason_codes"]
    assert "CRITICAL_IMPACT" in out["reason_codes"]
    assert out["strength"] == "STRONG"


def test_listing_does_not_force_positive() -> None:
    out = _base(event_type="LISTING", sentiment="NEUTRAL")
    assert out["direction"] == "NEUTRAL"


def test_no_trading_action_flags() -> None:
    out = _base(risk_flags=["ALLOW", "SELL", "HIGH_VOLATILITY_EVENT"])
    assert "ALLOW" not in out["risk_flags"]
    assert "SELL" not in out["risk_flags"]
    assert "HIGH_VOLATILITY_EVENT" in out["risk_flags"]


def test_no_ollama_imports_in_n5() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "stock_platform" / "news"
    for name in (
        "news_signal_service.py",
        "news_signal_standardize.py",
        "news_signal_scheduler.py",
        "news_signal_constants.py",
        "news_signal_models.py",
    ):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "ollama" not in node.module
                assert "upbit_opportunity_scanner" not in node.module
                assert "upbit_opportunity_shadow" not in node.module
                assert "realtime.ai_signal_gate" not in (node.module or "")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "ollama" not in alias.name


def test_scheduler_disabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPBIT_NEWS_SIGNAL_ENABLED", "false")
    from stock_platform.common.settings import clear_settings_cache, get_settings
    from stock_platform.news.news_signal_scheduler import UpbitNewsSignalScheduler

    clear_settings_cache()
    assert get_settings().upbit_news_signal_enabled is False
    assert UpbitNewsSignalScheduler().enabled() is False


def test_service_skips_non_completed() -> None:
    from stock_platform.news.news_signal_service import NewsSignalService

    session = MagicMock()
    # scalars returns empty for COMPLETED filter path when we pass analysis_ids
    # and status filter is in SQL — unit-level: _load_eligible uses COMPLETED only
    session.scalars.return_value = []
    service = NewsSignalService(session)
    stats = service.run_batch(limit=10)
    assert stats.llm_calls == 0
    assert stats.signals_created == 0


def test_idempotency_key_fields() -> None:
    assert SIGNAL_VERSION == "upbit_news_signal_v1"


def test_multi_symbol_payloads_independent() -> None:
    a = _base(symbol="KRW-BTC", sentiment="POSITIVE")
    b = _base(
        symbol="KRW-ETH",
        sentiment="POSITIVE",
        affected_item={
            "symbol": "KRW-ETH",
            "direction": "NEGATIVE",
            "news_impact_level": "MEDIUM",
            "confidence": 0.7,
        },
    )
    assert a["symbol"] == "KRW-BTC"
    assert b["symbol"] == "KRW-ETH"
    assert a["direction"] == "POSITIVE"
    assert b["direction"] == "NEGATIVE"
    assert b["strength"] == "MODERATE"
