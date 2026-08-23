"""Entry B1 Forward Validation — Baseline vs B1 (Shadow research only)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
    COHORT_LEGACY,
    COHORT_NEW,
    ENTRY_CANDIDATE_B1_SPEC,
    LEGACY_FORWARD_COUNT,
    NEXT_COLLECT,
    NEXT_REVIEW_FAIL,
    NEXT_REVIEW_PASS,
    TARGET_COMBINED_OPPORTUNITIES,
    TARGET_NEW_UNSEEN,
    VERDICT_COLLECTING,
    VERDICT_GATES_FAILED,
    VERDICT_REVIEW_READY,
    assign_cohorts,
    evaluate_promotion_gates,
    filter_attribution,
    run_b1_forward_validation,
    summarize_b1_forward_from_shadows,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_policy_ab import (
    ENTRY_BASELINE_SPEC,
    OpportunityMetrics,
    evaluate_entry_eligibility,
)
from stock_platform.operation.upbit_opportunity_shadow.pre_entry_features import (
    compute_pre_entry_features,
)
from stock_platform.operation.upbit_opportunity_shadow.candle_path import MinuteBar
from decimal import Decimal


def _metrics(*, rsi: float, vol: float = 0.9, sep: float = 0.1) -> OpportunityMetrics:
    return OpportunityMetrics(
        symbol="KRW-TEST",
        scanner_score=80.0,
        ai_recommendation="ALLOW",
        ma_separation_pct=sep,
        short_ma=101.0,
        long_ma=100.0,
        rsi14=rsi,
        volume_surge=vol,
    )


def _outcome(net: float, *, gross: float | None = None, fee: float = 10.0) -> dict:
    g = gross if gross is not None else (net + fee)
    return {
        "net_pnl_krw": net,
        "gross_pnl_krw": g,
        "estimated_fee_krw": fee,
        "net_return_pct": net / 100.0,
        "holding_seconds": 200,
        "exit_reason": "MA_DEAD_CROSS",
        "fee_only_loss": abs(g) < 1e-9 and net < 0,
    }


def _shadow(
    *,
    sid: int,
    rsi: float,
    vol: float,
    net: float,
    detected: datetime,
    return_5m: float = 0.0,
    mae: float = -0.1,
) -> SimpleNamespace:
    return SimpleNamespace(
        shadow_id=sid,
        symbol=f"KRW-S{sid % 7}",
        scanner_score=70,
        scanner_rank=1,
        recommendation="ALLOW",
        confidence=0.8,
        ma5=101.0,
        ma20=100.0,
        rsi14=rsi,
        volume_surge=vol,
        entry_price=Decimal("100"),
        entry_snapshot={"candidate": {"ma_spread_pct": 0.1}},
        evaluation_detail={
            "exit_ab": {"baseline": _outcome(net)},
        },
        return_5m_pct=return_5m,
        return_15m_pct=0.0,
        return_30m_pct=0.0,
        return_60m_pct=0.0,
        mfe_pct=0.5,
        mae_pct=mae,
        detected_at=detected,
        status="COMPLETED",
        deleted_at=None,
    )


def test_baseline_eligibility() -> None:
    ok, _ = evaluate_entry_eligibility(_metrics(rsi=70.0, vol=0.8), ENTRY_BASELINE_SPEC)
    bad, reason = evaluate_entry_eligibility(
        _metrics(rsi=70.01, vol=0.8), ENTRY_BASELINE_SPEC
    )
    assert ok is True
    assert bad is False
    assert reason == "RSI_TOO_HIGH"


def test_b1_rsi65_eligibility() -> None:
    ok, _ = evaluate_entry_eligibility(
        _metrics(rsi=65.0, vol=0.8), ENTRY_CANDIDATE_B1_SPEC
    )
    bad, reason = evaluate_entry_eligibility(
        _metrics(rsi=65.01, vol=0.8), ENTRY_CANDIDATE_B1_SPEC
    )
    assert ok is True
    assert bad is False
    assert reason == "RSI_TOO_HIGH"


def test_rsi_65_70_filtering() -> None:
    # Baseline pass, B1 fail
    m = _metrics(rsi=67.0, vol=0.8)
    b_ok, _ = evaluate_entry_eligibility(m, ENTRY_BASELINE_SPEC)
    b1_ok, _ = evaluate_entry_eligibility(m, ENTRY_CANDIDATE_B1_SPEC)
    assert b_ok is True
    assert b1_ok is False


def test_same_exit_policy_in_report() -> None:
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    rows = [
        _shadow(sid=1, rsi=60, vol=0.9, net=10, detected=t0),
        _shadow(sid=2, rsi=68, vol=0.9, net=-20, detected=t0 + timedelta(minutes=1)),
    ]
    report = run_b1_forward_validation(rows)
    assert report["policies"]["exit"]["tp_pct"] == 10.0
    assert report["policies"]["candidate_b_vol10_excluded"] is True
    assert report["mutations"]["REAL_POLICY_MUTATION"] == 0
    assert report["AUTO_PROMOTE"] is False


def test_legacy_new_sample_separation() -> None:
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    rows = [
        _shadow(
            sid=i,
            rsi=60,
            vol=0.9,
            net=1.0 if i % 2 == 0 else -1.0,
            detected=t0 + timedelta(minutes=i),
        )
        for i in range(LEGACY_FORWARD_COUNT + 3)
    ]
    obs = assign_cohorts(rows)
    assert len(obs) == LEGACY_FORWARD_COUNT + 3
    assert sum(1 for o in obs if o.cohort == COHORT_LEGACY) == LEGACY_FORWARD_COUNT
    assert sum(1 for o in obs if o.cohort == COHORT_NEW) == 3


def test_forward_outcome_and_fee() -> None:
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    rows = [_shadow(sid=1, rsi=60, vol=0.9, net=-15.0, detected=t0)]
    report = run_b1_forward_validation(rows)
    assert report["baseline"]["fees"] == 10.0
    assert report["baseline"]["net_pnl"] == -15.0


def test_avoided_missed_filter_benefit() -> None:
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    # rsi 67: baseline only — loser avoided
    # rsi 68: baseline only — winner missed
    # rsi 60: both
    rows = [
        _shadow(sid=1, rsi=67, vol=0.9, net=-50, detected=t0),
        _shadow(sid=2, rsi=68, vol=0.9, net=30, detected=t0 + timedelta(minutes=1)),
        _shadow(sid=3, rsi=60, vol=0.9, net=5, detected=t0 + timedelta(minutes=2)),
    ]
    obs = assign_cohorts(rows)
    attr = filter_attribution(obs)
    assert attr["avoided_losers"] == 1
    assert attr["avoided_loser_value"] == 50.0
    assert attr["missed_winners"] == 1
    assert attr["missed_winner_value"] == 30.0
    assert attr["net_filter_benefit"] == 20.0


def test_early_dump() -> None:
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    rows = [
        _shadow(
            sid=1, rsi=60, vol=0.9, net=-10, detected=t0, return_5m=-0.4
        ),
        _shadow(
            sid=2, rsi=60, vol=0.9, net=5, detected=t0 + timedelta(minutes=1), return_5m=0.1
        ),
    ]
    report = run_b1_forward_validation(rows)
    assert report["early_dump"]["baseline_early_dump_count"] == 1
    assert report["b1"]["early_dump_count"] == 1


def test_promotion_gate_sample_lt_1000() -> None:
    gates = evaluate_promotion_gates(
        combined_n=734,
        new_n=275,
        baseline={"net_pnl": -100, "profit_factor": 0.5, "max_loss": -50},
        b1={"net_pnl": 10, "profit_factor": 1.2, "max_loss": -40},
        early_base=0.3,
        early_b1=0.2,
        stability={"b1_beats_baseline_majority": True},
        concentration={"concentrated": False},
    )
    assert gates["FINAL_VERDICT"] == VERDICT_COLLECTING
    assert gates["NEXT_ACTION"] == NEXT_COLLECT
    assert gates["REAL_PROMOTION_RECOMMENDED"] == "NO"
    assert gates["AUTO_PROMOTE"] is False


def test_promotion_gate_net_le_0_reject() -> None:
    gates = evaluate_promotion_gates(
        combined_n=TARGET_COMBINED_OPPORTUNITIES,
        new_n=TARGET_NEW_UNSEEN,
        baseline={"net_pnl": -100, "profit_factor": 0.5, "max_loss": -50},
        b1={"net_pnl": -1, "profit_factor": 1.2, "max_loss": -40},
        early_base=0.3,
        early_b1=0.2,
        stability={"b1_beats_baseline_majority": True},
        concentration={"concentrated": False},
    )
    assert "C_b1_net_gt_0" in gates["PROMOTION_GATE_FAILURES"]
    assert gates["FINAL_VERDICT"] == VERDICT_GATES_FAILED
    assert gates["NEXT_ACTION"] == NEXT_REVIEW_FAIL


def test_promotion_gate_pf_le_1_reject() -> None:
    gates = evaluate_promotion_gates(
        combined_n=TARGET_COMBINED_OPPORTUNITIES,
        new_n=TARGET_NEW_UNSEEN,
        baseline={"net_pnl": -100, "profit_factor": 0.5, "max_loss": -50},
        b1={"net_pnl": 10, "profit_factor": 0.9, "max_loss": -40},
        early_base=0.3,
        early_b1=0.2,
        stability={"b1_beats_baseline_majority": True},
        concentration={"concentrated": False},
    )
    assert "D_b1_pf_gt_1" in gates["PROMOTION_GATE_FAILURES"]


def test_promotion_gate_new_sample_lt_500() -> None:
    gates = evaluate_promotion_gates(
        combined_n=TARGET_COMBINED_OPPORTUNITIES,
        new_n=100,
        baseline={"net_pnl": -100, "profit_factor": 0.5, "max_loss": -50},
        b1={"net_pnl": 10, "profit_factor": 1.2, "max_loss": -40},
        early_base=0.3,
        early_b1=0.2,
        stability={"b1_beats_baseline_majority": True},
        concentration={"concentrated": False},
    )
    assert gates["FINAL_VERDICT"] == VERDICT_COLLECTING
    assert "B_new_ge_500" in gates["PROMOTION_GATE_FAILURES"]


def test_all_gates_pass_review_ready_only() -> None:
    gates = evaluate_promotion_gates(
        combined_n=TARGET_COMBINED_OPPORTUNITIES,
        new_n=TARGET_NEW_UNSEEN,
        baseline={"net_pnl": -100, "profit_factor": 0.5, "max_loss": -50},
        b1={"net_pnl": 20, "profit_factor": 1.2, "max_loss": -40},
        early_base=0.3,
        early_b1=0.2,
        stability={"b1_beats_baseline_majority": True},
        concentration={"concentrated": False},
    )
    assert gates["all_gates_passed"] is True
    assert gates["FINAL_VERDICT"] == VERDICT_REVIEW_READY
    assert gates["NEXT_ACTION"] == NEXT_REVIEW_PASS
    assert gates["REAL_PROMOTION_RECOMMENDED"] == "NO"
    assert gates["AUTO_PROMOTE"] is False
    assert gates["PROMOTION_STATUS"] == "REVIEW READY"


def test_research_failure_fail_open() -> None:
    # summarize wrapper must not raise
    out = summarize_b1_forward_from_shadows([])
    assert out["REAL_PROMOTION_RECOMMENDED"] == "NO"
    assert out.get("AUTO_PROMOTE") is False


def test_pre_entry_features_from_bars() -> None:
    t0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(70):
        ts = t0 - timedelta(minutes=70 - i)
        px = Decimal(str(100 + i * 0.01))
        bars.append(
            MinuteBar(
                candle_at=ts,
                open=px,
                high=px + Decimal("0.1"),
                low=px - Decimal("0.1"),
                close=px,
            )
        )
    feat = compute_pre_entry_features(bars, entry_at=t0, entry_price=Decimal("101"))
    assert feat.get("ok") is True
    assert feat.get("pre_entry_return_5m") != "NOT_AVAILABLE"


def test_buckets_and_symbol_aggregation() -> None:
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    rows = [
        _shadow(sid=i, rsi=50 + (i % 20), vol=0.8 + (i % 5) * 0.2, net=-5 + i, detected=t0 + timedelta(minutes=i))
        for i in range(12)
    ]
    report = run_b1_forward_validation(rows)
    assert "RSI_EXHAUSTION" in report["exhaustion_patterns"]
    assert "MA_EXTENSION" in report["exhaustion_patterns"]
    assert "VOLUME_EXHAUSTION" in report["exhaustion_patterns"]
    assert "top_symbols" in report["symbol_concentration"]
    assert "EARLY" in report["time_stability"] or report["time_stability"]["compared_chunks"] >= 0
