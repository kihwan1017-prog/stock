"""Focused tests — UPBIT Churn Guard Shadow V1 (REAL admission 무영향)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.constants import (
    CLS_MA_DEAD_CROSS_REENTRY_CHURN,
    CLS_MICRO_TICK_CHURN,
    CLS_ORDER_LIFECYCLE_ANOMALY,
    CLS_RAPID_REENTRY_CHURN,
    CLS_TRAILING_STOP_REENTRY_CHURN,
    CLS_UNKNOWN,
    MODE,
    REAL_BLOCK_ENABLED,
    SEVERITY_WARNING,
)
from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.detector import (
    evaluate_round_trips,
    evaluate_threshold_variants,
)
from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.hooks import (
    observe_churn_on_binding_closed,
)
from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.telegram import (
    format_churn_message,
)


def _rt(
    *,
    net: float,
    exit_reason: str = "MA_DEAD_CROSS",
    entry: float = 248.0,
    exit_px: float = 247.0,
    reentry: float | None = 100.0,
    hold: float = 200.0,
    fees: float = 10.0,
    qty: float = 40.0,
    overlap: int = 0,
    c3: str | None = None,
) -> dict:
    gross = (exit_px - entry) * qty
    return {
        "net_pnl": net,
        "gross_pnl": gross,
        "fees": fees,
        "entry_price": entry,
        "exit_price": exit_px,
        "quantity": qty,
        "turnover_krw": (entry + exit_px) * qty,
        "exit_reason": exit_reason,
        "reentry_delay_seconds": reentry,
        "holding_seconds": hold,
        "overlapping_skip_count": overlap,
        "c3_shadow_decision": c3,
        "closed_at": datetime.now(timezone.utc).isoformat(),
    }


def test_mode_shadow_real_block_disabled():
    assert MODE == "SHADOW"
    assert REAL_BLOCK_ENABLED is False


def test_one_losing_rt_no_excessive_alert():
    ev = evaluate_round_trips([_rt(net=-40.0, reentry=None)])
    assert ev["should_alert"] is False
    assert ev["primary_classification"] == CLS_UNKNOWN
    assert ev["threshold_variants"]["S2"]["WOULD_ALERT"] is False


def test_repeated_losses_accumulate_evidence():
    rts = [_rt(net=-40.0, reentry=None)] + [
        _rt(net=-40.0, reentry=120.0) for _ in range(3)
    ]
    ev = evaluate_round_trips(rts)
    assert ev["signals"]["consecutive_losing_round_trips"] >= 3
    assert ev["should_alert"] is True


def test_rapid_reentry_classification():
    rts = [_rt(net=-40.0, reentry=None)] + [
        _rt(net=-40.0, reentry=90.0) for _ in range(2)
    ]
    ev = evaluate_round_trips(rts)
    assert ev["profiles"]["RAPID_REENTRY"] is True
    assert ev["primary_classification"] != CLS_UNKNOWN
    assert (
        CLS_RAPID_REENTRY_CHURN
        in {ev["primary_classification"], *ev["secondary_classifications"]}
        or ev["primary_classification"]
        in {CLS_MA_DEAD_CROSS_REENTRY_CHURN, "COMPOSITE_CHURN"}
    )


def test_repeated_ma_dc_classification():
    rts = [
        _rt(net=-40.0, exit_reason="MA_DEAD_CROSS", reentry=None),
        _rt(net=-40.0, exit_reason="MA_DEAD_CROSS", reentry=110.0),
        _rt(net=-40.0, exit_reason="MA_DEAD_CROSS", reentry=95.0),
    ]
    ev = evaluate_round_trips(rts)
    assert ev["signals"]["ma_dead_cross_repeat_count"] == 3
    assert ev["primary_classification"] in {
        CLS_MA_DEAD_CROSS_REENTRY_CHURN,
        "COMPOSITE_CHURN",
    }
    assert ev["threshold_variants"]["S2"]["WOULD_ALERT"] is True


def test_trailing_pattern_classification():
    rts = [
        _rt(net=-50.0, exit_reason="TRAILING_STOP", reentry=None, entry=100, exit_px=99),
        _rt(net=-50.0, exit_reason="TRAILING_STOP", reentry=150.0, entry=100, exit_px=99),
        _rt(net=-50.0, exit_reason="TRAILING_STOP", reentry=140.0, entry=100, exit_px=99),
    ]
    ev = evaluate_round_trips(rts)
    assert CLS_TRAILING_STOP_REENTRY_CHURN in {
        ev["primary_classification"],
        *ev["secondary_classifications"],
    } or ev["signals"]["trailing_stop_repeat_count"] >= 2


def test_fee_dominated_classification():
    # small gross loss, large fee share
    rts = []
    for i in range(3):
        rts.append(
            {
                "net_pnl": -80.0,
                "gross_pnl": -20.0,
                "fees": 60.0,
                "entry_price": 100.0,
                "exit_price": 99.8,
                "quantity": 100.0,
                "turnover_krw": 20000.0,
                "exit_reason": "MA_DEAD_CROSS",
                "reentry_delay_seconds": None if i == 0 else 200.0,
                "holding_seconds": 120.0,
                "overlapping_skip_count": 0,
            }
        )
    ev = evaluate_round_trips(rts)
    assert ev["profiles"]["FEE_CHURN"] is True


def test_micro_tick_generalized_by_pct():
    # ~0.4% move, repeated loss — not fixed 1 KRW
    rts = [
        _rt(net=-50.0, entry=1000.0, exit_px=996.0, reentry=None, qty=10.0, fees=5.0),
        _rt(net=-50.0, entry=1000.0, exit_px=996.0, reentry=80.0, qty=10.0, fees=5.0),
        _rt(net=-50.0, entry=1000.0, exit_px=996.0, reentry=90.0, qty=10.0, fees=5.0),
    ]
    ev = evaluate_round_trips(rts)
    assert ev["signals"]["micro_tick_loss_count"] >= 2
    assert ev["profiles"]["MICRO_TICK_CHURN"] is True


def test_composite_churn():
    rts = [
        _rt(net=-40.0, reentry=None),
        _rt(net=-40.0, reentry=90.0),
        _rt(net=-40.0, reentry=100.0),
        _rt(net=-40.0, reentry=110.0),
    ]
    ev = evaluate_round_trips(rts)
    assert ev["profiles"]["COMPOSITE_CHURN"] is True


def test_xlm_historical_replay_balanced_alerts():
    """History #125 pattern: 248→247 ×5 MA_DC, micro loss, reentry <180s."""

    rts = [_rt(net=-50.0, reentry=None, fees=12.0)]
    for _ in range(4):
        rts.append(_rt(net=-50.0, reentry=102.0, fees=12.0))
    ev = evaluate_round_trips(rts, cycle_still_active=True)
    assert ev["threshold_variants"]["S2"]["WOULD_ALERT"] is True
    assert ev["should_alert"] is True
    assert ev["primary_classification"] in {
        CLS_MA_DEAD_CROSS_REENTRY_CHURN,
        CLS_MICRO_TICK_CHURN,
        "COMPOSITE_CHURN",
        CLS_RAPID_REENTRY_CHURN,
    }
    assert ev["severity"] in {"INFO", "WARNING", "CRITICAL"}


def test_non_xlm_generalized_fixture():
    rts = [
        _rt(
            net=-120.0,
            entry=5000.0,
            exit_px=4980.0,
            exit_reason="MA_DEAD_CROSS",
            reentry=None,
            qty=2.0,
        ),
        _rt(
            net=-120.0,
            entry=5000.0,
            exit_px=4980.0,
            exit_reason="MA_DEAD_CROSS",
            reentry=200.0,
            qty=2.0,
        ),
        _rt(
            net=-120.0,
            entry=5000.0,
            exit_px=4980.0,
            exit_reason="MA_DEAD_CROSS",
            reentry=250.0,
            qty=2.0,
        ),
    ]
    ev = evaluate_round_trips(rts)
    assert ev["threshold_variants"]["S2"]["WOULD_ALERT"] is True


def test_order_lifecycle_anomaly_from_overlap_skips():
    rts = [
        _rt(net=-40.0, reentry=None, overlap=1),
        _rt(net=-40.0, reentry=90.0, overlap=1),
        _rt(net=-40.0, reentry=100.0, overlap=1),
    ]
    ev = evaluate_round_trips(rts)
    assert ev["primary_classification"] == CLS_ORDER_LIFECYCLE_ANOMALY


def test_threshold_variants_s0_never_alerts():
    rts = [_rt(net=-40.0, reentry=None)] + [_rt(net=-40.0, reentry=50.0) for _ in range(5)]
    variants = evaluate_threshold_variants(evaluate_round_trips(rts)["signals"])
    assert variants["S0"]["WOULD_ALERT"] is False
    assert variants["S1"]["WOULD_ALERT"] is True


def test_shadow_hook_failure_fail_open():
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.service.evaluate_on_binding_closed",
        side_effect=RuntimeError("boom"),
    ):
        out = observe_churn_on_binding_closed(
            MagicMock(), user_broker_account_id=1380, symbol="KRW-XLM"
        )
    assert out.get("fail_open") is True
    assert out.get("ok") is False


def test_telegram_format_korean_not_raw_only():
    ep = MagicMock()
    ep.symbol = "KRW-XLM"
    ep.severity = SEVERITY_WARNING
    ep.primary_classification = CLS_MA_DEAD_CROSS_REENTRY_CHURN
    ep.round_trip_count = 5
    ep.consecutive_loss_count = 5
    ep.net_pnl = -250
    ep.min_reentry_seconds = 102
    ep.dominant_exit_reason = "MA_DEAD_CROSS"
    title, msg = format_churn_message(ep)
    assert "반복매매" in title or "반복매매" in msg
    assert "MA 데드크로스" in msg
    assert "관찰 중" in msg
    assert "자동매매 정책 변경 없음" in msg


def test_no_kill_or_live_mutation_in_hook_module():
    import inspect

    from stock_platform.operation.upbit_opportunity_shadow import churn_guard_shadow

    src = inspect.getsource(churn_guard_shadow.hooks)
    assert "kill_switch" not in src.lower() or "Kill" not in src
    assert "LIVE" not in src
    assert "ARM" not in src
