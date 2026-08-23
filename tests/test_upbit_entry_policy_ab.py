"""Entry Policy A/B — Baseline vs Candidate B (Shadow only)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from stock_platform.operation.upbit_opportunity_shadow.entry_policy_ab import (
    ENTRY_BASELINE_SPEC,
    ENTRY_CANDIDATE_B_SPEC,
    FORWARD_SAMPLE_MIN,
    NEXT_COLLECT,
    VERDICT_RUNNING,
    OpportunityMetrics,
    decide_entry_candidate_b,
    evaluate_entry_eligibility,
    compare_entry_on_opportunity,
)


def _m(
    *,
    rsi: float,
    vol: float,
    sep: float = 0.1,
    ai: str = "ALLOW",
    short: float = 101.0,
    long: float = 100.0,
) -> OpportunityMetrics:
    return OpportunityMetrics(
        symbol="KRW-TEST",
        scanner_score=80.0,
        ai_recommendation=ai,
        ma_separation_pct=sep,
        short_ma=short,
        long_ma=long,
        rsi14=rsi,
        volume_surge=vol,
    )


def test_same_opportunity_ab() -> None:
    row = SimpleNamespace(
        shadow_id=1,
        symbol="KRW-AAA",
        scanner_score=70,
        recommendation="ALLOW",
        ma5=101.0,
        ma20=100.0,
        rsi14=60.0,
        volume_surge=1.2,
        entry_snapshot={"candidate": {"ma_spread_pct": 1.0}},
        evaluation_detail={
            "exit_ab": {
                "baseline": {
                    "net_pnl_krw": 10.0,
                    "gross_pnl_krw": 20.0,
                    "estimated_fee_krw": 10.0,
                    "net_return_pct": 0.1,
                    "holding_seconds": 200,
                    "exit_reason": "MA_DEAD_CROSS",
                    "fee_only_loss": False,
                }
            }
        },
        return_5m_pct=0.1,
        mfe_pct=0.5,
        mae_pct=-0.1,
    )
    obs = compare_entry_on_opportunity(row)
    assert obs is not None
    assert obs["same_opportunity"] is True
    assert obs["baseline_eligible"] is True
    assert obs["candidate_b_eligible"] is True
    assert obs["candidate_a_exit_used"] is False
    assert obs["exit_policy"]["tp_pct"] == 10.0


def test_rsi_boundary_65() -> None:
    ok65, _ = evaluate_entry_eligibility(
        _m(rsi=65.0, vol=1.0), ENTRY_CANDIDATE_B_SPEC
    )
    bad66, reason = evaluate_entry_eligibility(
        _m(rsi=65.01, vol=1.0), ENTRY_CANDIDATE_B_SPEC
    )
    assert ok65 is True
    assert bad66 is False
    assert reason == "RSI_TOO_HIGH"


def test_volume_boundary_1_0() -> None:
    ok, _ = evaluate_entry_eligibility(
        _m(rsi=60.0, vol=1.0), ENTRY_CANDIDATE_B_SPEC
    )
    bad, reason = evaluate_entry_eligibility(
        _m(rsi=60.0, vol=0.99), ENTRY_CANDIDATE_B_SPEC
    )
    assert ok is True
    assert bad is False
    assert reason == "VOLUME_SURGE_TOO_LOW"


def test_baseline_70_0_8() -> None:
    assert ENTRY_BASELINE_SPEC.rsi_max == 70.0
    assert ENTRY_BASELINE_SPEC.min_volume_surge == 0.8
    ok, _ = evaluate_entry_eligibility(
        _m(rsi=70.0, vol=0.8), ENTRY_BASELINE_SPEC
    )
    assert ok is True
    bad_rsi, r1 = evaluate_entry_eligibility(
        _m(rsi=70.01, vol=0.8), ENTRY_BASELINE_SPEC
    )
    bad_vol, r2 = evaluate_entry_eligibility(
        _m(rsi=70.0, vol=0.79), ENTRY_BASELINE_SPEC
    )
    assert bad_rsi is False and r1 == "RSI_TOO_HIGH"
    assert bad_vol is False and r2 == "VOLUME_SURGE_TOO_LOW"


def test_ai_allow_identical() -> None:
    assert ENTRY_BASELINE_SPEC.require_ai_allow is True
    assert ENTRY_CANDIDATE_B_SPEC.require_ai_allow is True
    bad, reason = evaluate_entry_eligibility(
        _m(rsi=50.0, vol=2.0, ai="BLOCK"), ENTRY_CANDIDATE_B_SPEC
    )
    assert bad is False
    assert reason == "AI_SELECTION_NOT_ALLOW"


def test_ma_separation_identical() -> None:
    assert (
        ENTRY_BASELINE_SPEC.min_ma_separation_pct
        == ENTRY_CANDIDATE_B_SPEC.min_ma_separation_pct
        == 0.05
    )
    bad, reason = evaluate_entry_eligibility(
        _m(rsi=50.0, vol=2.0, sep=0.04), ENTRY_BASELINE_SPEC
    )
    assert bad is False
    assert reason == "MA_SEPARATION_TOO_SMALL"


def test_exit_policy_baseline_only() -> None:
    assert ENTRY_CANDIDATE_B_SPEC.rsi_max == 65.0
    # Candidate B는 entry만 — exit 스펙 필드 없음
    assert not hasattr(ENTRY_CANDIDATE_B_SPEC, "tp_pct")


def test_insufficient_sample() -> None:
    d = decide_entry_candidate_b(
        opportunity_count=FORWARD_SAMPLE_MIN - 1,
        baseline_kpi={"net_pnl": -10, "profit_factor": 0.5, "max_trade_loss": -5, "sample_count": 50},
        candidate_kpi={"net_pnl": 10, "profit_factor": 1.2, "max_trade_loss": -4, "sample_count": 40},
        filter_delta={"filter_benefit_positive": True},
    )
    assert d["candidate_superiority"] == "INSUFFICIENT"
    assert d["final_verdict"] == VERDICT_RUNNING
    assert d["next_action"] == NEXT_COLLECT


def test_candidate_stricter_filters_baseline_pass() -> None:
    # RSI 68 / vol 0.9 → Baseline OK, Candidate B NO
    m = _m(rsi=68.0, vol=0.9)
    b_ok, _ = evaluate_entry_eligibility(m, ENTRY_BASELINE_SPEC)
    c_ok, reason = evaluate_entry_eligibility(m, ENTRY_CANDIDATE_B_SPEC)
    assert b_ok is True
    assert c_ok is False
    assert reason in {"RSI_TOO_HIGH", "VOLUME_SURGE_TOO_LOW"}
