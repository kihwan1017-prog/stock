"""Unit tests — CLEAN entry quality early-dump experiment (no REAL mutation)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
    CLEAN_FORWARD_EPOCH_START,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_b1_forward_validation import (
    ForwardObs,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_policy_ab import (
    OpportunityMetrics,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_quality_early_dump_experiment import (
    E1_RSI_MAX,
    REAL_14_REFERENCE,
    evaluate_filter_arm,
    outcome_label,
    run_entry_quality_early_dump_experiment,
    sample_gate,
    _pass_e1,
    _pass_e3,
)


def _metrics(**kwargs) -> OpportunityMetrics:
    base = dict(
        symbol="KRW-TEST",
        scanner_score=80.0,
        ai_recommendation="ALLOW",
        ma_separation_pct=0.2,
        short_ma=100.0,
        long_ma=99.0,
        rsi14=68.0,
        volume_surge=1.2,
    )
    base.update(kwargs)
    return OpportunityMetrics(**base)


def _obs(
    *,
    sid: int,
    net: float,
    early: bool = False,
    rsi: float = 68.0,
    pre5: float | str = "NOT_AVAILABLE",
    mfe: float | None = 0.1,
    mae: float | None = -0.2,
    r3: float | None = -0.4,
    r5: float | None = -0.5,
) -> ForwardObs:
    return ForwardObs(
        shadow_id=sid,
        symbol="KRW-TEST",
        detected_at=CLEAN_FORWARD_EPOCH_START + timedelta(hours=sid),
        cohort="CLEAN_FORWARD",
        metrics=_metrics(rsi14=rsi),
        outcome={
            "net_pnl_krw": net,
            "gross_pnl_krw": net + 10 if net < 0 else net + 5,
            "estimated_fee_krw": 10.0,
        },
        mfe_pct=mfe,
        mae_pct=mae,
        baseline_eligible=True,
        b1_eligible=rsi <= 65,
        early_dump=early,
        features={
            "ok": True,
            "pre_entry_return_5m": pre5,
            "pre_entry_return_3m": "NOT_AVAILABLE",
            "dist_from_15m_high_pct": -0.5,
            "return_3m": r3,
            "return_5m": r5,
        },
    )


def test_sample_gate_thresholds() -> None:
    assert sample_gate(0) == "COLLECTION_ONLY"
    assert sample_gate(99) == "COLLECTION_ONLY"
    assert sample_gate(100) == "DIAGNOSTIC_ONLY"
    assert sample_gate(500) == "PRIMARY_REVIEW"
    assert sample_gate(1000) == "RECOMMENDED_REVIEW"


def test_outcome_label_early_dump_3m() -> None:
    o = _obs(sid=1, net=-50, r3=-0.4, r5=-0.1, early=True)
    assert outcome_label(o) == "EARLY_DUMP_3M"


def test_e1_filters_high_rsi() -> None:
    high = _obs(sid=1, net=-40, rsi=68.0)
    low = _obs(sid=2, net=20, rsi=60.0)
    assert _pass_e1(high) is False
    assert _pass_e1(low) is True
    assert E1_RSI_MAX == 65.0


def test_e3_spike_rejection() -> None:
    spike = _obs(sid=1, net=-30, pre5=0.8)
    flat = _obs(sid=2, net=10, pre5=0.1)
    assert _pass_e3(spike) is False
    assert _pass_e3(flat) is True


def test_filter_arm_net_benefit() -> None:
    # Filter rejects loser (-100) and winner (+30) → benefit = 100 - 30 = 70
    pool = [
        _obs(sid=1, net=-100, rsi=70.0, early=True),
        _obs(sid=2, net=30, rsi=70.0),
        _obs(sid=3, net=10, rsi=60.0),
    ]
    arm = evaluate_filter_arm(
        pool, code="E1", name_ko="RSI", accept_fn=_pass_e1
    )
    assert arm["filtered"] == 2
    assert arm["accepted"] == 1
    assert arm["avoided_losers"] == 1
    assert arm["missed_winners"] == 1
    assert arm["net_filter_benefit"] == 70.0


def test_run_experiment_empty_clean() -> None:
    # No clean rows → collection
    report = run_entry_quality_early_dump_experiment([])
    assert report["CLEAN_SAMPLE_COUNT"] == 0
    assert report["SAMPLE_GATE"] == "COLLECTION_ONLY"
    assert report["REAL_PROMOTION_RECOMMENDED"] == "NO"
    assert report["AUTO_PROMOTE"] is False
    assert report["mutations"]["REAL_POLICY_MUTATION"] == 0
    assert report["REAL_14_REFERENCE"]["rt"] == REAL_14_REFERENCE["rt"]
    assert report["NEXT_ACTION"] == "COLLECT_MORE_CLEAN_FORWARD"


def test_run_experiment_with_synthetic_clean_rows() -> None:
    epoch = CLEAN_FORWARD_EPOCH_START + timedelta(hours=2)

    def _row(sid: int, rsi: float, net: float, pre5: float) -> SimpleNamespace:
        return SimpleNamespace(
            shadow_id=sid,
            symbol="KRW-AAA",
            detected_at=epoch,
            created_at=epoch,
            status="COMPLETED",
            recommendation="ALLOW",
            scanner_score=70,
            confidence=0.8,
            ma5=101.0,
            ma20=100.0,
            rsi14=rsi,
            volume_surge=1.1,
            entry_price=100.0,
            mfe_pct=0.1,
            mae_pct=-0.4,
            return_5m_pct=-0.4,
            return_15m_pct=-0.2,
            return_30m_pct=-0.1,
            return_60m_pct=0.0,
            entry_snapshot={
                "candidate": {"ma_spread_pct": 0.2},
                "entry_price_provenance": {
                    "ok": True,
                    "quality": "CANONICAL",
                    "source": "market.candle_minute",
                },
            },
            evaluation_detail={
                "exit_ab": {
                    "baseline": {
                        "net_pnl_krw": net,
                        "gross_pnl_krw": net,
                        "estimated_fee_krw": 10.0,
                        "holding_seconds": 200,
                    }
                },
                "entry_ab": {"baseline_eligible": True},
                "entry_forward_features": {
                    "ok": True,
                    "pre_entry_return_5m": pre5,
                    "pre_entry_return_3m": 0.1,
                    "dist_from_15m_high_pct": -0.5,
                },
                "windows": {
                    "5": {"status": "OK", "price": 99.5, "return_pct": -0.4},
                    "15": {"status": "OK", "price": 99.8, "return_pct": -0.2},
                    "30": {"status": "OK", "price": 99.9, "return_pct": -0.1},
                    "60": {"status": "OK", "price": 100.0, "return_pct": 0.0},
                },
            },
        )

    rows = [
        _row(1, 68.0, -50.0, 0.8),
        _row(2, 60.0, 20.0, 0.1),
        _row(3, 62.0, -10.0, 0.2),
    ]
    report = run_entry_quality_early_dump_experiment(rows)
    assert report["CLEAN_SAMPLE_COUNT"] >= 1
    assert "E0" in report["filters"]
    assert "E1" in report["filters"]
    assert report["REAL_PROMOTION_RECOMMENDED"] == "NO"
    assert all(v == 0 for v in report["mutations"].values())
