"""UPBIT autotrading AI Market Analysis Job — focused tests (실주문 없음)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.ai.market_analysis.autotrading_periodic import (
    is_analysis_fresh,
    resolve_analysis_reuse_seconds,
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


def test_resolve_reuse_defaults_below_interval_not_ttl():
    """reuse==interval이면 분석 지연으로 격 tick skip → 기본은 interval-grace."""

    settings = SimpleNamespace(
        autotrading_ai_analysis_interval_seconds=300.0,
        autotrading_ai_analysis_ttl_seconds=900.0,
        autotrading_ai_analysis_reuse_seconds=None,
    )
    # grace=min(120, max(30, 300*0.4))=120 → reuse=180
    assert resolve_analysis_reuse_seconds(settings) == 180.0
    # Gate TTL(900)보다 작고, 다음 300s tick(age≈250)에서 재실행 가능
    assert resolve_analysis_reuse_seconds(settings) < 300.0
    assert resolve_analysis_reuse_seconds(settings) < 900.0


def test_resolve_reuse_explicit_and_clamped_to_ttl():
    settings = SimpleNamespace(
        autotrading_ai_analysis_interval_seconds=300.0,
        autotrading_ai_analysis_ttl_seconds=900.0,
        autotrading_ai_analysis_reuse_seconds=1200.0,
    )
    assert resolve_analysis_reuse_seconds(settings) == 900.0
    settings.autotrading_ai_analysis_reuse_seconds = 180.0
    assert resolve_analysis_reuse_seconds(settings) == 180.0


def test_next_interval_tick_not_skipped_after_analysis_latency():
    """tick+300에서 age≈255(분석 45초 지연) → FRESH skip 없이 재분석 가능."""

    now = datetime(2026, 8, 13, 3, 0, 0, tzinfo=timezone.utc)
    analyzed = now - timedelta(seconds=255)
    row = SimpleNamespace(analyzed_at=analyzed)
    reuse = resolve_analysis_reuse_seconds(
        SimpleNamespace(
            autotrading_ai_analysis_interval_seconds=300.0,
            autotrading_ai_analysis_ttl_seconds=900.0,
            autotrading_ai_analysis_reuse_seconds=None,
        )
    )
    assert reuse == 180.0
    assert is_analysis_fresh(row, ttl_seconds=reuse, now=now) is False
    # 동일 tick 직후(age=10)는 여전히 skip
    assert (
        is_analysis_fresh(
            SimpleNamespace(analyzed_at=now - timedelta(seconds=10)),
            ttl_seconds=reuse,
            now=now,
        )
        is True
    )
    # Gate TTL freshness는 유지 (900)
    assert is_analysis_fresh(row, ttl_seconds=900.0, now=now) is True


def test_is_analysis_fresh_timezone_naive_analyzed_at():
    now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
    naive = SimpleNamespace(
        analyzed_at=datetime(2026, 8, 12, 11, 55, 0)  # naive UTC 가정
    )
    assert is_analysis_fresh(naive, ttl_seconds=900, now=now) is True


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
            autotrading_ai_analysis_reuse_seconds=None,
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
    assert out["reuse_seconds"] == 180.0
    assert out["orders_created"] == 0


@pytest.mark.asyncio
async def test_run_once_refreshes_when_older_than_reuse_but_within_ttl(
    monkeypatch,
):
    """age=600 (reuse=300, ttl=900) → skip하지 않고 재분석 경로 진입."""

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
            autotrading_ai_analysis_reuse_seconds=None,
            autotrading_ai_min_confidence=0.4,
            autotrading_ai_analysis_provider="ollama",
            autotrading_ai_analysis_model="qwen3.5:4b",
            ollama_model="qwen3.5:4b",
            ollama_timeout_seconds=120.0,
            autotrading_ai_analysis_timeout_seconds=120.0,
            autotrading_ai_analysis_warmup_enabled=False,
        ),
    )
    now = datetime.now(timezone.utc)
    mid_age = SimpleNamespace(
        market_analysis_id=157,
        analyzed_at=now - timedelta(seconds=600),
        analysis_status="VALIDATED_WITH_WARNINGS",
    )
    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.find_latest_validated",
        lambda *a, **k: mid_age,
    )
    # TTL 기준으론 아직 fresh
    assert is_analysis_fresh(mid_age, ttl_seconds=900, now=now) is True
    assert is_analysis_fresh(mid_age, ttl_seconds=300, now=now) is False

    session = MagicMock()
    session.scalar.return_value = None  # no duplicate bucket
    job = UpbitAutotradingAiAnalysisJob(session)

    async def _ensure_prompt(*a, **k):
        return {"ok": True, "already_active": True, "version_id": 1, "schema_ok": True}

    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.ensure_chart_prompt_active",
        _ensure_prompt,
    )
    async def _candles_fail(*a, **k):
        return {"ok": False, "count": 0, "min_required": 30}

    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.ensure_minute_candles",
        _candles_fail,
    )
    out = await job.run_once(now=now)
    # candle 부족으로 실패해도 skip이 아니어야 함 (재분석 시도)
    assert out.get("skipped") is not True
    assert out.get("skip_reason") != "FRESH_RESULT_EXISTS"
    assert out["reuse_seconds"] == 180.0


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


@pytest.mark.asyncio
async def test_run_once_skips_when_ollama_circuit_open(monkeypatch):
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
            autotrading_ai_analysis_warmup_enabled=False,
            ollama_model="qwen3.5:4b",
            ollama_timeout_seconds=120.0,
        ),
    )
    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.find_latest_validated",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic._ollama_circuit_snapshot",
        lambda: {"allow": False, "state": "OPEN", "failure_count": 3},
    )
    session = MagicMock()
    session.scalar.return_value = None

    async def _prompt(session):
        return {"ok": True}

    async def _candle(*a, **k):
        return {"ok": True, "count": 60}

    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.ensure_chart_prompt_active",
        _prompt,
    )
    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.ensure_minute_candles",
        _candle,
    )
    monkeypatch.setattr(
        "stock_platform.ai.market_analysis.autotrading_periodic.resolve_news_sentiment",
        lambda *a, **k: "NO_DATA",
    )
    out = await UpbitAutotradingAiAnalysisJob(session).run_once(force=True)
    assert out["skipped"] is True
    assert out["skip_reason"] == "OLLAMA_CIRCUIT_OPEN"
    assert out["ok"] is False


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
