"""Profitability Improvement Shadow Lab V1 — focused tests (SHADOW ONLY)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.candidate_ranking import (
    rank_universe,
    score_a1_momentum_quality,
    score_a3_trend_confirmation,
)
from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.exit_engine import (
    PathSnapshot,
    evaluate_variant_exit,
    mfe_adaptive_trail_dd,
)
from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.reentry_engine import (
    decide_reentry_block,
)
from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.constants import (
    VARIANT_B0,
    VARIANT_B1,
    VARIANT_B2,
    VARIANT_B3,
    VARIANT_C1,
    VARIANT_C2,
    VARIANT_C3,
)


def _row(symbol: str, **kw):
    base = {
        "symbol": symbol,
        "rank": kw.pop("rank", 1),
        "score": kw.pop("score", 70.0),
        "liquidity": kw.pop("liquidity", 1e10),
        "technical_metrics": {
            "ma5": kw.pop("ma5", 100.0),
            "ma20": kw.pop("ma20", 98.0),
            "macd": kw.pop("macd", 0.1),
            "rsi14": kw.pop("rsi14", 55.0),
            "atr14": kw.pop("atr14", 1.0),
            "volume_surge": kw.pop("volume_surge", 1.2),
            "trend": kw.pop("trend", "UP"),
            "momentum": kw.pop("momentum", 1.0),
            "volatility": kw.pop("volatility", 1.0),
        },
    }
    return base


def test_candidate_no_future_leakage():
    rows = [_row("KRW-AAA", score=80), _row("KRW-BBB", score=60, rank=2)]
    with pytest.raises(ValueError, match="future_leakage"):
        rank_universe([{**rows[0], "return_30m": 1.0}], variant="A1")


def test_candidate_deterministic_top10_stable():
    rows = [_row(f"KRW-X{i}", score=50 + i, rank=i) for i in range(15)]
    a = rank_universe(rows, variant="A0", top_n=10)
    b = rank_universe(rows, variant="A0", top_n=10)
    assert [x["symbol"] for x in a] == [x["symbol"] for x in b]
    assert len(a) == 10
    assert a[0]["shadow_rank"] == 1


def test_overextension_penalty_lowers_a1():
    mild = _row("KRW-M", rsi14=55, volume_surge=1.2, ma5=101, ma20=100)
    hot = _row("KRW-H", rsi14=82, volume_surge=3.5, ma5=110, ma20=100)
    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.candidate_ranking import (
        extract_features,
    )

    assert score_a1_momentum_quality(extract_features(mild)) > score_a1_momentum_quality(
        extract_features(hot)
    )


def test_trend_confirmation_prefers_ma_alignment():
    good = _row("KRW-G", ma5=105, ma20=100, macd=0.2, rsi14=55)
    bad = _row("KRW-B", ma5=95, ma20=100, macd=-0.2, rsi14=80, trend="DOWN")
    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.candidate_ranking import (
        extract_features,
    )

    assert score_a3_trend_confirmation(extract_features(good)) > score_a3_trend_confirmation(
        extract_features(bad)
    )


def test_exit_sl_priority_never_deferred():
    snap = PathSnapshot(
        entry_price=Decimal("100"),
        current_price=Decimal("96"),  # -4% > 3% SL
        peak_price=Decimal("101"),
        hold_seconds=10,
        mfe_pct=1.0,
        mae_pct=-4.0,
        short_ma=Decimal("101"),
        long_ma=Decimal("99"),
        macd=0.1,
    )
    for vid in (VARIANT_B0, VARIANT_B1, VARIANT_B2, VARIANT_B3):
        d = evaluate_variant_exit(snap, vid)
        assert d.should_exit and d.exit_reason == "STOP_LOSS"
        assert not d.defer


def test_fee_aware_profit_lock_defers_micro_trailing():
    # trailing would fire but gain below fee+buffer
    snap = PathSnapshot(
        entry_price=Decimal("100"),
        current_price=Decimal("100.05"),  # tiny gain
        peak_price=Decimal("101.2"),  # armed
        hold_seconds=5,
        mfe_pct=1.2,
        mae_pct=-0.1,
    )
    d0 = evaluate_variant_exit(snap, VARIANT_B0)
    d1 = evaluate_variant_exit(snap, VARIANT_B1)
    assert d0.should_exit and d0.exit_reason == "TRAILING_STOP"
    assert d1.defer and d1.defer_reason == "FEE_AWARE_PROFIT_LOCK"


def test_mfe_adaptive_buckets_deterministic():
    assert mfe_adaptive_trail_dd(0.1) == 1.5
    assert mfe_adaptive_trail_dd(0.5) == 1.0
    assert mfe_adaptive_trail_dd(1.2) == 0.6


def test_ma_state_defers_strong_uptrend_trailing():
    snap = PathSnapshot(
        entry_price=Decimal("100"),
        current_price=Decimal("101.1"),
        peak_price=Decimal("102.0"),
        hold_seconds=120,
        mfe_pct=2.0,
        mae_pct=-0.2,
        short_ma=Decimal("101"),
        long_ma=Decimal("99"),
        macd=0.2,
        ma_dead_cross=False,
    )
    d3 = evaluate_variant_exit(snap, VARIANT_B3)
    assert d3.defer and d3.defer_reason == "MA_STATE_TREND_INTACT"


def test_reentry_cooldown_boundaries():
    assert decide_reentry_block(variant_id=VARIANT_C1, delay_seconds=59.9)["WOULD_BLOCK"] is True
    assert decide_reentry_block(variant_id=VARIANT_C1, delay_seconds=60.0)["WOULD_BLOCK"] is False
    assert decide_reentry_block(variant_id=VARIANT_C2, delay_seconds=179.9)["WOULD_BLOCK"] is True
    assert decide_reentry_block(variant_id=VARIANT_C2, delay_seconds=180.0)["WOULD_BLOCK"] is False


def test_reentry_c2_c3_divergence_fixture():
    """동일 delay>=180에서 C3 confirmation 없으면 block, 있으면 allow → 분화."""

    delay = 200.0
    c2 = decide_reentry_block(variant_id=VARIANT_C2, delay_seconds=delay)
    c3_block = decide_reentry_block(
        variant_id=VARIANT_C3,
        delay_seconds=delay,
        context={"new_signal": False, "ma_improved": False, "momentum_reset": False, "score_improved": False},
    )
    c3_allow = decide_reentry_block(
        variant_id=VARIANT_C3,
        delay_seconds=delay,
        context={"score_improved": True},
    )
    assert c2["WOULD_BLOCK"] is False
    assert c3_block["WOULD_BLOCK"] is True
    assert c3_allow["WOULD_BLOCK"] is False


def test_reentry_c3_unknown_context_diverges_from_c2():
    """UNKNOWN이면 날조하지 않고 C2(allow)와 다른 결정."""

    delay = 250.0
    c2 = decide_reentry_block(variant_id=VARIANT_C2, delay_seconds=delay)
    c3 = decide_reentry_block(
        variant_id=VARIANT_C3,
        delay_seconds=delay,
        context={
            "new_signal": "UNKNOWN",
            "ma_improved": "UNKNOWN",
            "momentum_reset": "UNKNOWN",
            "score_improved": "UNKNOWN",
        },
    )
    assert c2["WOULD_BLOCK"] is False
    assert c3["WOULD_BLOCK"] is True
    assert c3["REASON"] == "CONTEXTUAL_CONFIRMATION_UNKNOWN"


def test_lineage_tri_state_and_price_path_keys():
    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.lineage import (
        PRICE_PATH_HORIZONS_SEC,
        _tri_state,
    )

    assert _tri_state(None) == "UNKNOWN"
    assert _tri_state("UNKNOWN") == "UNKNOWN"
    assert _tri_state(True) is True
    assert _tri_state(False) is False
    assert PRICE_PATH_HORIZONS_SEC == (30, 60, 180, 300)


def test_candidate_variants_distinct_ranks_with_features():
    rows = [
        _row("KRW-AAA", score=90, rsi14=50, momentum=2.0, volume_surge=1.1, ma5=101, ma20=100),
        _row("KRW-BBB", score=88, rsi14=82, momentum=4.0, volume_surge=3.5, ma5=110, ma20=100),
        _row("KRW-CCC", score=70, rsi14=45, momentum=0.5, volume_surge=1.0, ma5=99, ma20=100, trend="DOWN"),
        _row("KRW-DDD", score=60, rsi14=55, momentum=1.0, volume_surge=1.2, ma5=102, ma20=100),
    ]
    a0 = [x["symbol"] for x in rank_universe(rows, variant="A0", top_n=4)]
    a1 = [x["symbol"] for x in rank_universe(rows, variant="A1", top_n=4)]
    assert a0 != a1  # overextension penalty가 A1 순위 변경


def test_ma_dc_d0_baseline_equality():
    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.ma_dc_engine import (
        MaDcSnapshot,
        decide_d0_baseline,
        decide_d1_confirmed,
        decide_d3_mfe_aware,
    )

    snap = MaDcSnapshot(
        entry_price=100.0,
        baseline_exit_price=99.0,
        current_price=99.0,
        short_ma=98.0,
        long_ma=100.0,
    )
    d0 = decide_d0_baseline(snap)
    assert d0["WOULD_EXIT"] is True
    assert d0["EXIT_PRICE"] == 99.0
    assert d0["DELAY_MINUTES"] == 0.0


def test_ma_dc_stop_loss_precedence():
    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.ma_dc_engine import (
        MaDcSnapshot,
        decide_d1_confirmed,
        decide_d3_mfe_aware,
    )

    snap = MaDcSnapshot(
        entry_price=100.0,
        baseline_exit_price=99.0,
        current_price=96.0,
        short_ma=95.0,
        long_ma=100.0,
        stop_loss_hit=True,
        minutes_since_baseline=5.0,
        confirmed_dead_cross=False,
    )
    assert decide_d1_confirmed(snap)["REASON"] == "STOP_LOSS_PRECEDENCE"
    assert decide_d3_mfe_aware(snap)["REASON"] == "STOP_LOSS_PRECEDENCE"


def test_ma_dc_max_hold_precedence():
    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.ma_dc_engine import (
        MaDcSnapshot,
        decide_d2_slope_separation,
    )

    snap = MaDcSnapshot(
        entry_price=100.0,
        baseline_exit_price=99.0,
        current_price=99.5,
        short_ma=99.0,
        long_ma=100.0,
        max_hold_hit=True,
        minutes_since_baseline=360.0,
    )
    assert decide_d2_slope_separation(snap)["REASON"] == "MAX_HOLD_PRECEDENCE"


def test_shadow_hooks_never_raise_on_bad_session():
    """hooks fail-open — exception swallow."""

    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow import (
        hooks,
    )

    class Boom:
        def scalar(self, *a, **k):
            raise RuntimeError("boom")

        def add(self, *a, **k):
            raise RuntimeError("boom")

        def flush(self):
            raise RuntimeError("boom")

    # must not raise
    hooks.observe_candidate_selection(
        Boom(),  # type: ignore[arg-type]
        user_broker_account_id=1380,
        scanner_run_id="x",
        selection_id=1,
        strategy_id=1,
        observed_at=datetime.now(timezone.utc),
        universe_rows=[],
    )
    hooks.enroll_binding_on_open(
        Boom(),  # type: ignore[arg-type]
        user_broker_account_id=1380,
        binding_id=1,
        symbol="KRW-BTC",
        strategy_id=1,
        entry_order_id=1,
        entry_at=datetime.now(timezone.utc),
        entry_price=Decimal("1"),
    )
    hooks.finalize_binding_on_close(
        Boom(),  # type: ignore[arg-type]
        binding_id=1,
        exit_at=datetime.now(timezone.utc),
    )
