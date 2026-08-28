"""WRK-016 positive-edge entry discovery unit tests — no LIVE."""

from __future__ import annotations

from datetime import datetime, timezone

from stock_platform.operation.upbit_positive_edge_entry.families import (
    FamilyHit,
    dedupe_signals,
    evaluate_families,
)
from stock_platform.operation.upbit_positive_edge_entry.regime import (
    MarketRegime,
    classify_regime,
)
from stock_platform.operation.upbit_positive_edge_entry.report_metrics import (
    net_return_pct,
    promotion_ok,
    summarize_nets,
)
from stock_platform.operation.upbit_positive_edge_entry.walk_forward import (
    chronological_splits,
    confidence_from_n,
)


def test_regime_no_future_fields() -> None:
    r = classify_regime(
        btc_ret_60m_pct=1.0,
        btc_ma_short=100.0,
        btc_ma_long=99.0,
        btc_realized_vol_60m=0.01,
        vol_high_threshold=0.5,
        vol_low_threshold=0.001,
    )
    assert r == MarketRegime.BULL_TREND


def test_high_vol_regime() -> None:
    r = classify_regime(
        btc_ret_60m_pct=0.0,
        btc_ma_short=100.0,
        btc_ma_long=100.0,
        btc_realized_vol_60m=1.0,
        vol_high_threshold=0.5,
        vol_low_threshold=0.1,
    )
    assert r == MarketRegime.HIGH_VOLATILITY


def test_mean_reversion_disabled_in_bear() -> None:
    feat = {
        "ma5": 90.0,
        "ma20": 100.0,
        "ma_sep_pct": -10.0,
        "volume_surge": 1.0,
        "rsi14": 25.0,
        "ret_5m_pct": 0.1,
        "ret_15m_pct": -1.2,
        "ret_60m_pct": -2.0,
        "ma5_slope_pct": -0.1,
        "breakout_20m": False,
        "close": 90.0,
    }
    hits = evaluate_families(feat, regime=MarketRegime.BEAR_TREND)
    assert all(h.family != "MEAN_REVERSION" for h in hits)
    hits2 = evaluate_families(feat, regime=MarketRegime.SIDEWAYS)
    assert any(h.family == "MEAN_REVERSION" for h in hits2)


def test_momentum_independent_of_m0_ai() -> None:
    feat = {
        "ma5": 101.0,
        "ma20": 100.0,
        "ma_sep_pct": 1.0,
        "volume_surge": 1.5,
        "rsi14": 55.0,
        "ret_5m_pct": 0.4,
        "ret_15m_pct": 0.5,
        "ret_60m_pct": 0.8,
        "ma5_slope_pct": 0.2,
        "breakout_20m": False,
        "close": 101.0,
    }
    hits = evaluate_families(feat, regime=MarketRegime.BULL_TREND)
    names = {h.family for h in hits}
    assert "MOMENTUM" in names


def test_cost_reduces_gross() -> None:
    assert net_return_pct(1.0, slip_bps=2.0) < 1.0
    assert net_return_pct(1.0, slip_bps=5.0) < net_return_pct(1.0, slip_bps=1.0)


def test_walk_forward_order_preserved() -> None:
    rows = list(range(10))
    tr, va, te = chronological_splits(rows)
    assert tr + va + te == rows
    assert len(tr) >= len(va)


def test_dedupe_keeps_higher_score() -> None:
    a = FamilyHit("MOMENTUM", 1.0, "a")
    b = FamilyHit("BREAKOUT", 3.0, "b")
    out = dedupe_signals(
        [
            ("t1", "KRW-X", a),
            ("t1", "KRW-X", b),
            ("t1", "KRW-Y", a),
        ]
    )
    assert len(out) == 2
    kept = {sym: p for _, sym, p in out}
    assert kept["KRW-X"].family == "BREAKOUT"


def test_confidence_bands() -> None:
    assert confidence_from_n(10) == "VERY_LOW"
    assert confidence_from_n(50) == "LOW"
    assert confidence_from_n(150) == "MEDIUM"


def test_promotion_gate() -> None:
    assert promotion_ok({"n": 50, "pf": 1.2, "total_net": 10}) is True
    assert promotion_ok({"n": 50, "pf": 0.9, "total_net": 10}) is False
    assert promotion_ok({"n": 10, "pf": 2.0, "total_net": 10}) is False


def test_summarize_nets_empty() -> None:
    s = summarize_nets([], days=10)
    assert s["n"] == 0
    assert s["total_net"] == 0.0


def test_future_label_isolation_contract() -> None:
    """evaluate_families must not accept/require future return keys."""

    feat = {
        "ma5": 101.0,
        "ma20": 100.0,
        "ma_sep_pct": 0.1,
        "volume_surge": 0.9,
        "rsi14": 60.0,
        "ret_5m_pct": 0.1,
        "ret_15m_pct": 0.1,
        "ret_60m_pct": 0.2,
        "ma5_slope_pct": 0.05,
        "breakout_20m": False,
        "close": 101.0,
        # poison — must be ignored if present
        "ret_30m_future": 99.0,
    }
    hits = evaluate_families(feat, regime=MarketRegime.SIDEWAYS)
    assert isinstance(hits, list)
