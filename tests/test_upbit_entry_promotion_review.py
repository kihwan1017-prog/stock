"""Entry 최종 승격 리뷰 — profitability / preference 분류."""

from __future__ import annotations

from stock_platform.operation.upbit_opportunity_shadow.entry_policy_promotion_review import (
    NEXT_COLLECT,
    VERDICT_B1_NOT_PROFITABLE,
    VERDICT_READY,
    decide_promotion,
)


def _arm(
    *,
    net: float,
    pf: float | None,
    entries: int = 100,
    filter_benefit: float = 0.0,
    max_loss: float = -100.0,
    fees: float = 50.0,
) -> dict:
    abs_ok = net > 0
    pf_ok = pf is not None and pf > 1.0
    return {
        "net_pnl": net,
        "profit_factor": pf,
        "entries": entries,
        "max_single_loss": max_loss,
        "fees": fees,
        "filter_vs_baseline": {"net_filter_benefit": filter_benefit},
        "ABSOLUTE_NET_PROFITABLE": "YES" if abs_ok else "NO",
        "PROFIT_FACTOR_ABOVE_1": "YES" if pf_ok else "NO",
    }


def test_b1_preferred_but_not_profitable() -> None:
    d = decide_promotion(
        baseline=_arm(net=-7000, pf=0.5),
        b1=_arm(net=-2600, pf=0.7, filter_benefit=4000),
        b=_arm(net=-3600, pf=0.52, filter_benefit=3500),
        stability={"b1_beats_baseline_all_chunks": True, "b_beats_baseline_all_chunks": True},
        bootstrap={
            "b1_beats_baseline_rate": 0.9,
            "b_beats_baseline_rate": 0.85,
            "b1_stable_vs_baseline": True,
            "b_stable_vs_baseline": True,
        },
    )
    assert d["PREFERRED_ENTRY_CANDIDATE"] == "RSI65_VOL08"
    assert d["FINAL_VERDICT"] == VERDICT_B1_NOT_PROFITABLE
    assert d["REAL_PROMOTION_RECOMMENDED"] == "NO"
    assert d["NEXT_ACTION"] == NEXT_COLLECT
    assert d["ABSOLUTE_NET_PROFITABLE"] == "NO"


def test_ready_when_absolutely_profitable() -> None:
    d = decide_promotion(
        baseline=_arm(net=-100, pf=0.9),
        b1=_arm(net=50, pf=1.2, filter_benefit=100),
        b=_arm(net=20, pf=1.1, filter_benefit=80),
        stability={"b1_beats_baseline_all_chunks": True, "b_beats_baseline_all_chunks": True},
        bootstrap={
            "b1_beats_baseline_rate": 0.95,
            "b_beats_baseline_rate": 0.9,
            "b1_stable_vs_baseline": True,
            "b_stable_vs_baseline": True,
        },
    )
    assert d["FINAL_VERDICT"] == VERDICT_READY
    assert d["REAL_PROMOTION_RECOMMENDED"] == "YES"
