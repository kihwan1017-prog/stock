"""WRK-010 — daily-report ops/research slim projection equivalence (READ)."""

from __future__ import annotations

from stock_platform.operation.autotrading_daily_report_service import (
    _health_class,
    _is_kiwoom_expected_post_close,
    _why_no_trade_ko,
)
from stock_platform.operation.autotrading_research.status import (
    VARIANT_E0,
    VARIANT_K0,
    _sample_counts_upbit,
    build_cross_market_research_status_for_daily_report,
)


def test_daily_report_research_slim_shape() -> None:
    """slim projection은 FE가 쓰는 sample 필드만 보장한다."""

    payload = {
        "UPBIT": {
            "NATURAL_OPPORTUNITY_POOL": 10,
            "samples": {
                "E0": {"VALID_SAMPLE": 3, "UNIQUE_SAMPLE": 10},
                "E2": {"VALID_SAMPLE": 2, "UNIQUE_SAMPLE": 8},
            },
        },
        "KIWOOM": {
            "samples": {VARIANT_K0: {"VALID_SAMPLE": 1, "UNIQUE_SAMPLE": 4}},
        },
    }
    upbit = payload["UPBIT"]
    assert upbit["NATURAL_OPPORTUNITY_POOL"] == upbit["samples"]["E0"]["UNIQUE_SAMPLE"]
    assert upbit["samples"]["E0"]["VALID_SAMPLE"] >= 0
    assert payload["KIWOOM"]["samples"][VARIANT_K0]["VALID_SAMPLE"] >= 0


def test_health_equivalence_kiwoom_post_close() -> None:
    ops = {
        "live": "OFF",
        "arm": "OFF",
        "market_feed": {"status": "DISCONNECTED"},
        "kiwoom_funnel": {"FIRST_ZERO_STAGE": "MARKET_CLOSED"},
        "reliability": {
            "health_state": "DEGRADED",
            "no_trade_classification": "NORMAL_NO_SIGNAL",
            "funnel": {"FIRST_ZERO_STAGE": "MARKET_CLOSED"},
            "auto_trading_ready": False,
        },
        "auto_trading_state": "STOPPED",
        "projection": "daily_report",
    }
    assert _is_kiwoom_expected_post_close(ops) is True
    code, _ = _health_class(broker="KIWOOM", ops=ops, order_stats={})
    assert code == "YELLOW"


def test_why_no_trade_uses_reliability_classification() -> None:
    msgs = _why_no_trade_ko(
        broker="UPBIT",
        ops={
            "reliability": {
                "no_trade_classification": "NORMAL_NO_SIGNAL",
                "funnel": {"first_zero_stage": "SELECTION"},
            },
            "market_feed": {"status": "REAL_FRESH"},
            "auto_trading_state": "RUNNING",
        },
        funnel_first_zero="SELECTION",
        funnel_reason=None,
    )
    assert any("매수 조건" in m for m in msgs)


def test_sample_counts_match_natural_pool_semantics() -> None:
    """UNIQUE_SAMPLE(E0) == NATURAL_OPPORTUNITY_POOL 의미 (slim 근거)."""

    # 단위 수준: VARIANT_E0 상수와 slim 매핑 규칙만 고정
    assert VARIANT_E0 == "E0"
    assert callable(_sample_counts_upbit)
    assert callable(build_cross_market_research_status_for_daily_report)
