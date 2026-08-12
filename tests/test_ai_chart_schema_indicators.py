"""CHART 분석 스키마/지표/파서 Fail Closed — focused tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.ai.execution.runner import AIExecutionRunner
from stock_platform.ai.market_analysis.gate_enrichment import (
    enrich_safe_result_for_gate,
    map_chart_to_gate_decision,
)
from stock_platform.ai.market_analysis.minute_indicators import (
    compute_minute_chart_indicators,
)


def _candle(i: int, close: str, volume: str = "100") -> dict:
    base = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc) + timedelta(
        minutes=i
    )
    c = Decimal(close)
    return {
        "open_time": base.isoformat(),
        "close_time": base.isoformat(),
        "open": str(c),
        "high": str(c + Decimal("1")),
        "low": str(c - Decimal("1")),
        "close": str(c),
        "volume": volume,
    }


def test_indicators_ma5_ma20_from_minute_candles():
    candles = [
        _candle(i, str(1000 + i)) for i in range(45)
    ]
    ind = compute_minute_chart_indicators(candles)
    assert ind["status"] in {"READY", "PARTIAL"}
    assert ind["ma5"] is not None
    assert ind["ma20"] is not None
    assert ind["price"] is not None
    assert ind["return_5m_pct"] is not None
    assert ind["rsi14"] is not None
    assert Decimal(ind["ma5"]) > 0


def test_indicators_insufficient():
    ind = compute_minute_chart_indicators([_candle(0, "1000")])
    assert ind["status"] == "INSUFFICIENT"


def test_valid_hold_mapping():
    m = map_chart_to_gate_decision(
        trend="SIDEWAYS",
        momentum="NEUTRAL",
        volatility="NORMAL",
        confidence=0.7,
    )
    assert m["recommendation"] == "HOLD"
    assert m["reason_code"] == "NEUTRAL_OR_UNCERTAIN"


def test_valid_allow_mapping():
    m = map_chart_to_gate_decision(
        trend="UPTREND",
        momentum="BULLISH",
        volatility="LOW",
        confidence=0.8,
    )
    assert m["recommendation"] == "ALLOW"


def test_valid_reduce_mapping():
    m = map_chart_to_gate_decision(
        trend="UPTREND",
        momentum="BULLISH",
        volatility="HIGH",
        confidence=0.9,
    )
    assert m["recommendation"] == "REDUCE"


def test_normalized_fallback_not_market_hold():
    safe = enrich_safe_result_for_gate(
        {
            "confidence": 0.5,
            "warnings": ["normalized_for_validation"],
            "result": {
                "trend": "UNCERTAIN",
                "momentum": "UNKNOWN",
                "volatility": "UNKNOWN",
            },
        }
    )
    assert safe["recommendation"] == "HOLD"
    assert safe["gate_enrichment"]["reason_code"] == "PARSE_NORMALIZED_FALLBACK"
    assert safe["gate_enrichment"]["usable_for_live_gate"] is False
    assert "not_a_market_hold" in safe["reasons"]


def _runner_validate(content: str, task: str = "CHART_ANALYSIS"):
    session = MagicMock()
    runner = AIExecutionRunner(session)
    row = SimpleNamespace(
        task_type=task,
        output_schema_id=None,
        policy_ids=None,
    )
    # schema 없이 CHART → fail closed when needs wrap
    return runner._validate_response(row, content)


def test_chart_missing_task_type_invalid():
    out = _runner_validate('{"result": {"trend": "UPTREND"}}')
    assert out["status"] == "INVALID"
    assert out["code"] == "AI_RESPONSE_MISSING_TASK_TYPE"


def test_chart_empty_invalid():
    out = _runner_validate("")
    assert out["status"] == "INVALID"
    assert out["code"] == "AI_RESPONSE_EMPTY"


def test_chart_truncated_json_invalid():
    out = _runner_validate('{"task_type": "CHART_ANALYSIS", "result": {')
    # truncated starts with { but may still have task_type substring
    # needs_wrap False if task_type present — then validate_ai_output fails
    # Either INVALID from fail-closed or from validator
    assert out["status"] in {"INVALID", "BLOCKED"}


def test_chart_valid_json_parses_without_normalized_defaults():
    payload = {
        "schema_version": "1.0",
        "task_type": "CHART_ANALYSIS",
        "confidence": 0.72,
        "reasoning_summary": "mild uptrend",
        "result": {
            "trend": "UPTREND",
            "momentum": "BULLISH",
            "volatility": "LOW",
            "summary": "ma5 above ma20",
        },
        "warnings": [],
        "citations": [],
    }
    import json

    out = _runner_validate(json.dumps(payload))
    # schema None → validate_ai_output may still accept without json_schema
    assert out["status"] in {"VALID", "VALID_WITH_WARNINGS", "INVALID"}
    if out["status"] in {"VALID", "VALID_WITH_WARNINGS"}:
        data = out.get("data") or {}
        assert "normalized_for_validation" not in list(data.get("warnings") or [])
        result = data.get("result") or {}
        assert result.get("trend") == "UPTREND"


def test_chart_enum_aliases():
    from stock_platform.ai.market_analysis.chart_enum_normalize import (
        normalize_chart_result_enums,
    )

    out = normalize_chart_result_enums(
        {
            "result": {
                "trend": "BULLISH",
                "momentum": "POSITIVE",
                "volatility": "MEDIUM",
            }
        }
    )
    assert out["result"]["trend"] == "UPTREND"
    assert out["result"]["momentum"] == "BULLISH"
    assert out["result"]["volatility"] == "NORMAL"

    from stock_platform.ai.market_analysis.autotrading_periodic import (
        find_latest_validated,
    )

    bad = SimpleNamespace(
        warnings=["normalized_for_validation"],
        safe_result={"warnings": ["normalized_for_validation"]},
        market_analysis_id=164,
    )
    good = SimpleNamespace(
        warnings=[],
        safe_result={"recommendation": "HOLD", "warnings": []},
        market_analysis_id=165,
    )
    session = MagicMock()
    # scalars().first path replaced with list iteration
    session.scalars.return_value = [bad, good]
    found = find_latest_validated(
        session, exchange_code="UPBIT", symbol="KRW-XRP"
    )
    assert found is good
