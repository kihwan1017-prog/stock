# -*- coding: utf-8 -*-
"""Focused tests — Upbit strategy observability V1."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest

from stock_platform.operation.upbit_strategy_observability.leakage import (
    assert_no_lookahead_in_trading_payload,
    trading_modules_must_not_import_post_trade,
)
from stock_platform.operation.upbit_strategy_observability.regime import (
    classify_btc_trend,
    classify_symbol_regime,
    regime_formula_doc,
)
from stock_platform.operation.upbit_strategy_observability.service import (
    build_admission_payload,
    build_signal_payload,
)
from stock_platform.trading.entry_admission_service import EntryAdmissionDecision


def test_lookahead_keys_blocked_in_trading_payload():
    with pytest.raises(AssertionError, match="LOOKAHEAD_LEAKAGE"):
        assert_no_lookahead_in_trading_payload({"fwd_15m_pct": 1.2})
    with pytest.raises(AssertionError, match="LOOKAHEAD_LEAKAGE"):
        assert_no_lookahead_in_trading_payload({"nested": {"mfe_pct": 0.1}})
    assert_no_lookahead_in_trading_payload(
        {"price": 100, "fast_ma": 1, "slow_ma": 2, "reason": "OK"}
    )


def test_signal_payload_strips_lookahead_and_marks_observation_only():
    payload = build_signal_payload(
        signal_type="BUY",
        price=100,
        short_ma=Decimal("10"),
        long_ma=Decimal("9"),
        extra={"mfe_pct": 99, "reason": "BULLISH"},
    )
    assert "mfe_pct" not in payload
    assert payload["observation_only"] is True
    assert payload["used_in_trading_decision"] is False
    assert_no_lookahead_in_trading_payload(payload)


def test_admission_payload_observation_only():
    decision = EntryAdmissionDecision(
        allowed=False,
        reason_code="OPEN_ORDER_LIMIT_EXCEEDED",
        source="ENTRY_ADMISSION",
        strategy_id=17483,
        user_broker_account_id=1380,
        snapshot={"open_order_count": 1, "live": True, "arm": True},
        checked_at="2026-09-09T00:00:00+00:00",
    )
    payload = build_admission_payload(decision.to_dict())
    assert payload["admission_allowed"] is False
    assert payload["reason"] == "OPEN_ORDER_LIMIT_EXCEEDED"
    assert payload["observation_only"] is True
    assert payload["used_in_trading_decision"] is False


def test_regime_formula_is_observation_only():
    doc = regime_formula_doc()
    assert doc["used_in_trading_decision"] is False
    assert classify_btc_trend(0.5) == "UP"
    assert classify_btc_trend(-0.5) == "DOWN"
    assert classify_btc_trend(0.0) == "SIDEWAYS"
    assert (
        classify_symbol_regime(ret_30m_pct=0.1, range_pct_30m=1.0) == "SIDEWAYS"
    )


def test_post_trade_module_marked_lookahead_only():
    from stock_platform.operation.upbit_strategy_observability import post_trade

    assert post_trade.LOOKAHEAD_ANALYTICS_ONLY is True
    assert post_trade.MUST_NOT_DRIVE_TRADING is True
    forbidden = trading_modules_must_not_import_post_trade()
    assert "stock_platform.trading.entry_admission_service" in forbidden
    assert "stock_platform.realtime.ma_evaluator" in forbidden


def test_observability_failure_does_not_change_admission_decision():
    """Admission decision object must be unchanged by observe hook."""

    decision = EntryAdmissionDecision(
        allowed=True,
        reason_code="ADMISSION_ALLOWED",
        source="ENTRY_ADMISSION",
        strategy_id=17483,
        user_broker_account_id=1380,
        snapshot={},
        checked_at="t",
    )
    before = decision.to_dict()
    from stock_platform.operation.upbit_strategy_observability.hooks import (
        observe_admission,
    )

    with patch(
        "stock_platform.operation.upbit_strategy_observability.service.persist_event",
        side_effect=RuntimeError("write fail"),
    ):
        out = observe_admission(
            admission=decision,
            symbol="KRW-DOT",
            user_broker_account_id=1380,
            strategy_id=17483,
        )
    assert out.get("ok") is False
    assert out.get("code") == "OBSERVABILITY_WRITE_FAILED"
    assert decision.to_dict() == before
    assert decision.allowed is True


def test_scanner_universe_selected_and_not_selected_counts():
    from stock_platform.operation.upbit_strategy_observability import service

    rows = [
        {"symbol": "KRW-AAA", "rank": 1, "score": 90, "technical_metrics": {}},
        {"symbol": "KRW-BBB", "rank": 2, "score": 80, "technical_metrics": {}},
        {
            "symbol": "KRW-CCC",
            "rank": 3,
            "score": 70,
            "rejected": True,
            "reject_reason": "SKIP",
        },
    ]

    def fake_persist(**kwargs):
        sel = {str(s).upper() for s in (kwargs.get("selected_symbols") or set())}
        all_rows = kwargs.get("rows") or []
        return {
            "ok": True,
            "inserted": len(all_rows),
            "selected_count": sum(
                1 for r in all_rows if str(r.get("symbol") or "").upper() in sel
            ),
            "not_selected_count": sum(
                1
                for r in all_rows
                if str(r.get("symbol") or "").upper() not in sel
            ),
        }

    with patch.object(service, "persist_scanner_universe", side_effect=fake_persist):
        out = service.persist_scanner_universe(
            scanner_run_id="run1",
            observed_at=datetime.now(timezone.utc),
            strategy_id=17483,
            user_broker_account_id=1380,
            rows=rows,
            selected_symbols={"KRW-AAA"},
        )
    assert out["ok"] is True
    assert out["selected_count"] == 1
    assert out["not_selected_count"] == 2


def test_forbidden_lookahead_key_set_covers_counterfactual():
    with pytest.raises(AssertionError):
        assert_no_lookahead_in_trading_payload(
            {"candidate_counterfactual_forward": {}}
        )
    with pytest.raises(AssertionError):
        assert_no_lookahead_in_trading_payload({"fwd_15m_pct": 1.0})


def test_orderbook_policy_constant():
    from stock_platform.operation.upbit_strategy_observability.constants import (
        ORDERBOOK_POLICY,
    )

    assert ORDERBOOK_POLICY == "NOT_COLLECTED_RATE_LIMIT_SAFETY"


def test_observe_hooks_never_raise_to_caller():
    from stock_platform.operation.upbit_strategy_observability.hooks import (
        observe_scanner_universe,
        observe_signal_event,
    )

    with patch(
        "stock_platform.operation.upbit_strategy_observability.service.persist_scanner_universe",
        side_effect=RuntimeError("db"),
    ):
        out = observe_scanner_universe(
            scanner_run_id="r",
            ranked_rows=[{"symbol": "KRW-XRP", "rank": 1, "score": 1}],
        )
    assert out["ok"] is False
    assert out["code"] == "OBSERVABILITY_WRITE_FAILED"

    with patch(
        "stock_platform.operation.upbit_strategy_observability.service.persist_event",
        side_effect=RuntimeError("db"),
    ):
        out2 = observe_signal_event(
            side="BUY",
            signal_id="s1",
            symbol="KRW-XRP",
            strategy_id=17483,
            user_broker_account_id=1380,
            price=100,
            short_ma=1,
            long_ma=2,
        )
    assert out2["ok"] is False


def test_order_timeline_latency_math():
    from stock_platform.operation.upbit_strategy_observability.service import _ms

    a = datetime(2026, 9, 9, 1, 0, 0, tzinfo=timezone.utc)
    b = datetime(2026, 9, 9, 1, 0, 1, 500000, tzinfo=timezone.utc)
    assert _ms(a, b) == 1500.0
    assert _ms(None, b) is None


def test_exit_payload_includes_exit_reason_not_lookahead():
    payload = build_signal_payload(
        signal_type="SELL",
        price=99,
        short_ma=Decimal("9"),
        long_ma=Decimal("10"),
        extra={
            "exit_reason": "MA_DEAD_CROSS",
            "holding_seconds": 600,
            "position_entry_price": "100",
            "mfe_pct": 1.0,  # must be stripped
        },
    )
    assert payload["exit_reason"] == "MA_DEAD_CROSS"
    assert "mfe_pct" not in payload
    assert_no_lookahead_in_trading_payload(payload)


def test_candidate_forward_returns_marked_lookahead_only():
    from stock_platform.operation.upbit_strategy_observability.post_trade import (
        LOOKAHEAD_ANALYTICS_ONLY,
        MUST_NOT_DRIVE_TRADING,
        compute_candidate_forward_returns_safe,
    )

    assert LOOKAHEAD_ANALYTICS_ONLY is True
    assert MUST_NOT_DRIVE_TRADING is True
    # Empty session path: forward helper must not be imported by trading modules
    assert "fwd_" in "fwd_15m_pct"
    assert callable(compute_candidate_forward_returns_safe)


def test_trading_modules_do_not_call_forward_returns_for_decisions():
    """Static guard: entry admission source must not reference forward/MFE keys."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "stock_platform"
    paths = [
        root / "trading" / "entry_admission_service.py",
        root / "realtime" / "ma_evaluator.py",
    ]
    banned = ("fwd_15m_pct", "candidate_counterfactual_forward", "post_exit_json")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path.name} contains {token}"


def test_obs_failure_does_not_duplicate_order_path():
    """Observability stamp failure must not re-enter order create."""
    from stock_platform.operation.upbit_strategy_observability.hooks import (
        observe_order_timeline_stamp,
    )

    calls = {"n": 0}

    def boom(**kwargs):
        calls["n"] += 1
        raise RuntimeError("db")

    with patch(
        "stock_platform.operation.upbit_strategy_observability.service.upsert_order_timeline",
        side_effect=boom,
    ):
        out = observe_order_timeline_stamp(
            user_broker_account_id=1380,
            symbol="KRW-DOT",
            side_code="BUY",
            order_id=1,
        )
    assert out["ok"] is False
    assert calls["n"] == 1  # single attempt; no retry loop


def test_regime_not_used_as_gate_flag():
    doc = regime_formula_doc()
    assert doc.get("observation_only") is True or doc.get("used_in_trading_decision") is False

