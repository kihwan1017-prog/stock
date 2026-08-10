"""UPBIT autotrading AI Market Analysis Job — focused tests (실주문 없음)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.ai.market_analysis.autotrading_periodic import (
    is_analysis_fresh,
    time_bucket,
)
from stock_platform.ai.market_analysis.gate_enrichment import (
    enrich_safe_result_for_gate,
    map_chart_to_gate_decision,
    validate_gate_recommendation_fields,
)


def test_map_bullish_allow():
    m = map_chart_to_gate_decision(
        trend="UPTREND",
        momentum="BULLISH",
        volatility="LOW",
        confidence=0.8,
    )
    assert m["recommendation"] == "ALLOW"
    assert m["validated_mapping"] is True


def test_map_high_vol_reduce():
    m = map_chart_to_gate_decision(
        trend="UPTREND",
        momentum="BULLISH",
        volatility="HIGH",
        confidence=0.9,
    )
    assert m["recommendation"] == "REDUCE"


def test_map_bearish_hold():
    m = map_chart_to_gate_decision(
        trend="DOWNTREND",
        momentum="BEARISH",
        volatility="NORMAL",
        confidence=0.7,
    )
    assert m["recommendation"] == "HOLD"


def test_map_low_confidence_hold():
    m = map_chart_to_gate_decision(
        trend="UPTREND",
        momentum="BULLISH",
        volatility="LOW",
        confidence=0.1,
        min_confidence=0.4,
    )
    assert m["recommendation"] == "HOLD"
    assert m["reason_code"] == "LOW_CONFIDENCE"


def test_map_confidence_out_of_range():
    m = map_chart_to_gate_decision(
        trend="UPTREND",
        momentum="BULLISH",
        volatility="LOW",
        confidence=1.5,
    )
    assert m["recommendation"] == "HOLD"
    assert m["validated_mapping"] is False


def test_enrich_adds_news_no_data():
    safe = enrich_safe_result_for_gate(
        {
            "confidence": 0.7,
            "result": {
                "trend": "SIDEWAYS",
                "momentum": "NEUTRAL",
                "volatility": "NORMAL",
                "summary": "range",
            },
        },
        news_sentiment="NO_DATA",
    )
    assert safe["recommendation"] == "HOLD"
    assert safe["news_sentiment"] == "NO_DATA"
    assert safe["gate_enrichment"]["source"] == "chart_field_mapping_v1"
    assert validate_gate_recommendation_fields(safe) == []


def test_validate_malformed_recommendation():
    errs = validate_gate_recommendation_fields(
        {"recommendation": "BUY", "confidence": 0.5}
    )
    assert "INVALID_RECOMMENDATION" in errs


def test_time_bucket_stable():
    now = datetime(2026, 8, 10, 12, 0, 30, tzinfo=timezone.utc)
    b1 = time_bucket(now, 300)
    b2 = time_bucket(now + timedelta(seconds=100), 300)
    b3 = time_bucket(now + timedelta(seconds=301), 300)
    assert b1 == b2
    assert b3 == b1 + 1


def test_is_analysis_fresh():
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(analyzed_at=now - timedelta(seconds=100))
    assert is_analysis_fresh(row, ttl_seconds=900, now=now) is True
    stale = SimpleNamespace(analyzed_at=now - timedelta(seconds=1200))
    assert is_analysis_fresh(stale, ttl_seconds=900, now=now) is False
    assert is_analysis_fresh(None, ttl_seconds=900, now=now) is False


@pytest.mark.asyncio
async def test_run_once_skips_fresh(monkeypatch):
    from stock_platform.ai.market_analysis.autotrading_periodic import (
        UpbitAutotradingAiAnalysisJob,
    )

    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.get_settings",
        lambda: SimpleNamespace(
            autotrading_ai_analysis_symbol="KRW-XRP",
            autotrading_ai_analysis_timeframe="1m",
            autotrading_ai_analysis_interval_seconds=300.0,
            autotrading_ai_analysis_ttl_seconds=900.0,
            autotrading_ai_min_confidence=0.4,
            autotrading_ai_analysis_provider="ollama",
            autotrading_ai_analysis_model="qwen3.5:4b",
            ollama_model="qwen3.5:4b",
            ollama_timeout_seconds=120.0,
        ),
    )
    fresh_row = SimpleNamespace(
        market_analysis_id=42,
        analyzed_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.find_latest_validated",
        lambda *a, **k: fresh_row,
    )
    job = UpbitAutotradingAiAnalysisJob(MagicMock())
    out = await job.run_once()
    assert out["skipped"] is True
    assert out["skip_reason"] == "FRESH_RESULT_EXISTS"
    assert out["orders_created"] == 0


@pytest.mark.asyncio
async def test_run_once_missing_candle(monkeypatch):
    from stock_platform.ai.market_analysis.autotrading_periodic import (
        UpbitAutotradingAiAnalysisJob,
    )

    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.get_settings",
        lambda: SimpleNamespace(
            autotrading_ai_analysis_symbol="KRW-XRP",
            autotrading_ai_analysis_timeframe="1m",
            autotrading_ai_analysis_interval_seconds=300.0,
            autotrading_ai_analysis_ttl_seconds=900.0,
            autotrading_ai_min_confidence=0.4,
            autotrading_ai_analysis_provider="ollama",
            autotrading_ai_analysis_model="qwen3.5:4b",
            ollama_model="qwen3.5:4b",
            ollama_timeout_seconds=120.0,
        ),
    )
    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.find_latest_validated",
        lambda *a, **k: None,
    )
    session = MagicMock()
    session.scalar.return_value = None

    async def _prompt(session):
        return {"ok": True}

    async def _candle(*a, **k):
        return {"ok": False, "count": 5, "min_required": 30}

    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.ensure_chart_prompt_active",
        _prompt,
    )
    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.ensure_minute_candles",
        _candle,
    )
    out = await UpbitAutotradingAiAnalysisJob(session).run_once(force=True)
    assert out["ok"] is False
    assert out["error"] == "MISSING_OR_STALE_CANDLE"


def test_gate_lookup_helper(monkeypatch):
    from stock_platform.ai.market_analysis.autotrading_periodic import (
        snapshot_latest_for_gate_lookup,
    )

    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.get_settings",
        lambda: SimpleNamespace(autotrading_ai_analysis_ttl_seconds=900.0),
    )
    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.find_latest_validated",
        lambda *a, **k: SimpleNamespace(
            market_analysis_id=7,
            analyzed_at=datetime.now(timezone.utc),
            confidence=0.66,
            provider_code="ollama",
            model="qwen3.5:4b",
            trend_classification="UPTREND",
            safe_result={
                "recommendation": "ALLOW",
                "risk_level": "LOW",
                "news_sentiment": "NO_DATA",
                "reasons": ["trend=UPTREND"],
                "summary": "ok",
            },
        ),
    )
    snap = snapshot_latest_for_gate_lookup(MagicMock(), symbol="KRW-XRP")
    assert snap["status"] == "AI_ANALYSIS_FOUND"
    assert snap["fresh"] is True
    assert snap["recommendation"] == "ALLOW"


def test_no_news_does_not_fail_enrichment():
    safe = enrich_safe_result_for_gate(
        {
            "confidence": 0.55,
            "result": {
                "trend": "UPTREND",
                "momentum": "BULLISH",
                "volatility": "NORMAL",
                "summary": "up",
            },
        },
        news_sentiment="NO_DATA",
    )
    assert safe["recommendation"] == "ALLOW"
    assert safe["news_sentiment"] == "NO_DATA"
