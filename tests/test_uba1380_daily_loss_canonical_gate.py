# -*- coding: utf-8 -*-
"""UBA1380 daily-loss false-positive fix — focused regression (A–K)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline
from stock_platform.risk_engine.strategy_daily_loss_entry_gate import (
    resolve_canonical_strategy_id,
    reset_daily_loss_telegram_dedupe_for_tests,
    should_emit_daily_loss_telegram,
    should_suppress_auto_buy_for_daily_loss,
    strategy_owned_daily_loss_hit,
    trading_date_kst,
)


@pytest.fixture(autouse=True)
def _clear_tg_dedupe() -> None:
    reset_daily_loss_telegram_dedupe_for_tests()


# A — strategy_id numeric + strategy_code label
def test_a_resolve_prefers_numeric_strategy_id() -> None:
    sid = resolve_canonical_strategy_id(
        strategy_id=17483,
        strategy_code="PORTFOLIO_BULLISH_STATE_ENTRY",
    )
    assert sid == 17483


def test_a_reason_string_never_becomes_strategy_id() -> None:
    assert (
        resolve_canonical_strategy_id(
            strategy_id="PORTFOLIO_BULLISH_STATE_ENTRY",
            strategy_code="PORTFOLIO_BULLISH_STATE_ENTRY",
        )
        is None
    )


def test_a_metadata_numeric_fallback() -> None:
    assert (
        resolve_canonical_strategy_id(
            strategy_id=None,
            metadata={"strategy_id": 17483},
            strategy_code="PORTFOLIO_BULLISH_STATE_ENTRY",
        )
        == 17483
    )


# B — loss 1491 << limit 10M → not hit
def test_b_canonical_loss_under_limit_allows() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.risk_engine.strategy_daily_loss_entry_gate."
        "StrategyOwnedRiskService"
    ) as Svc:
        Svc.return_value.strategy_daily_loss_breached.return_value = (
            False,
            {
                "current_loss_amount": "1490.97",
                "loss_limit_amount": "10000000.00",
            },
        )
        hit, detail = strategy_owned_daily_loss_hit(
            session,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            strategy_id=17483,
            deployment_id=None,
            limit=Decimal("10000000"),
        )
    assert hit is False
    assert detail["mode"] == "STRATEGY_OWNED"
    assert detail["source"] == "STRATEGY_OWNED"


# C — account LIMIT_REACHED telemetry 있어도 AUTO 는 STRATEGY_OWNED
def test_c_account_telemetry_does_not_block_strategy_owned_auto() -> None:
    session = MagicMock()
    pipe = LiveOrderSafetyPipeline(session)
    with patch(
        "stock_platform.risk_engine.strategy_daily_loss_entry_gate."
        "strategy_owned_daily_loss_hit",
        return_value=(
            False,
            {
                "mode": "STRATEGY_OWNED",
                "source": "STRATEGY_OWNED",
                "current_loss_amount": "1490.97",
            },
        ),
    ):
        hit, detail = pipe._strategy_or_legacy_daily_loss_breached(
            user_broker_account_id=1380,
            broker_code="UPBIT",
            strategy_id="17483",
            strategy_deployment_id=None,
            limit=Decimal("10000000"),
            order_source="AUTO",
        )
    assert hit is False
    assert detail["mode"] == "STRATEGY_OWNED"


def test_c_legacy_sticky_limit_reached_ignored_when_under_policy() -> None:
    """MANUAL + sticky LIMIT_REACHED but loss < policy → 차단하지 않음."""
    session = MagicMock()
    row = SimpleNamespace(
        status_code="LIMIT_REACHED",
        current_loss_amount=Decimal("3405286.52"),
    )
    session.scalar.return_value = row
    pipe = LiveOrderSafetyPipeline(session)
    hit, detail = pipe._strategy_or_legacy_daily_loss_breached(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id="PORTFOLIO_BULLISH_STATE_ENTRY",
        strategy_deployment_id=None,
        limit=Decimal("10000000"),
        order_source="MANUAL",
    )
    assert hit is False
    assert detail["mode"] == "LEGACY_ACCOUNT"
    assert detail["sticky_limit_reached_ignored_for_policy"] is True


# D — canonical loss >= limit → block
def test_d_canonical_loss_hit_blocks() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.risk_engine.strategy_daily_loss_entry_gate."
        "StrategyOwnedRiskService"
    ) as Svc:
        Svc.return_value.strategy_daily_loss_breached.return_value = (
            True,
            {"current_loss_amount": "10000000.00"},
        )
        hit, _ = strategy_owned_daily_loss_hit(
            session,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            strategy_id=17483,
            deployment_id=None,
            limit=Decimal("10000000"),
        )
    assert hit is True


# E — upstream suppress when hit
def test_e_upstream_suppress_on_hit() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.risk_engine.strategy_daily_loss_entry_gate."
        "strategy_owned_daily_loss_hit",
        return_value=(True, {"mode": "STRATEGY_OWNED", "current_loss_amount": "1"}),
    ):
        suppress, detail = should_suppress_auto_buy_for_daily_loss(
            session,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            strategy_id=17483,
            deployment_id=None,
            limit=Decimal("1"),
        )
    assert suppress is True
    assert detail["reason_code"] == "DAILY_LOSS_LIMIT_REACHED"


def test_e_upstream_no_suppress_when_safe() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.risk_engine.strategy_daily_loss_entry_gate."
        "strategy_owned_daily_loss_hit",
        return_value=(False, {"mode": "STRATEGY_OWNED"}),
    ):
        suppress, detail = should_suppress_auto_buy_for_daily_loss(
            session,
            user_broker_account_id=1380,
            broker_code="UPBIT",
            strategy_id=17483,
            deployment_id=None,
            limit=Decimal("10000000"),
        )
    assert suppress is False
    assert detail["suppress"] is False


# F — SELL/protective: suppress helper is BUY-only; identity missing → fail closed for BUY
def test_f_missing_strategy_id_suppresses_buy_only_contract() -> None:
    session = MagicMock()
    suppress, detail = should_suppress_auto_buy_for_daily_loss(
        session,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=None,
        deployment_id=None,
        limit=Decimal("10000000"),
    )
    assert suppress is True
    assert detail["reason_code"] == "STRATEGY_IDENTITY_INVALID"


# G — KST next day telegram reset
def test_g_telegram_dedupe_resets_next_kst_day() -> None:
    day = trading_date_kst()
    assert should_emit_daily_loss_telegram(
        user_broker_account_id=1380, trading_day=day
    )
    assert not should_emit_daily_loss_telegram(
        user_broker_account_id=1380, trading_day=day
    )
    nxt = day + timedelta(days=1)
    assert should_emit_daily_loss_telegram(
        user_broker_account_id=1380, trading_day=nxt
    )


# H — AUTO invalid identity → fail closed, no LEGACY
def test_h_auto_invalid_strategy_identity_fail_closed() -> None:
    session = MagicMock()
    pipe = LiveOrderSafetyPipeline(session)
    hit, detail = pipe._strategy_or_legacy_daily_loss_breached(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id="PORTFOLIO_BULLISH_STATE_ENTRY",
        strategy_deployment_id=None,
        limit=Decimal("10000000"),
        order_source="AUTO",
    )
    assert hit is True
    assert detail["mode"] == "STRATEGY_IDENTITY_INVALID"
    session.scalar.assert_not_called()  # LEGACY account_daily_loss 미조회


# I — telegram storm 방지
def test_i_telegram_no_storm_same_day() -> None:
    day = date(2026, 9, 8)
    emits = [
        should_emit_daily_loss_telegram(
            user_broker_account_id=1380, trading_day=day
        )
        for _ in range(5)
    ]
    assert emits == [True, False, False, False, False]


# J — e6edf9d managed-symbol regression (existing decision contract)
def test_j_managed_symbol_regression_still_blocks_open_slot() -> None:
    from stock_platform.trading.symbol_ownership.constants import (
        SKIP_AUTO_ALREADY_MANAGED,
    )
    from stock_platform.trading.symbol_ownership.decision import (
        OwnershipFacts,
        decide_ownership,
    )

    d = decide_ownership(
        OwnershipFacts(auto_slot_active=True, auto_slot_occupies_entry=True)
    )
    assert d.entry_allowed is False
    assert d.entry_skip_reason == SKIP_AUTO_ALREADY_MANAGED


# K — executor passes numeric strategy_id (source inspection)
def test_k_executor_no_longer_assigns_reason_as_strategy_code() -> None:
    import inspect

    from stock_platform.realtime import risk_integrated_order_executor as mod

    src = inspect.getsource(mod.RiskIntegratedRealtimeOrderExecutor)
    assert "strategy_code=signal.reason_code" not in src
    assert "strategy_id=canonical_strategy_id" in src
    assert "should_suppress_auto_buy_for_daily_loss" in src


def test_execution_service_no_strategy_code_as_identity_fallback() -> None:
    import inspect

    from stock_platform.order import execution_service as mod

    src = inspect.getsource(mod.OrderExecutionService)
    # evaluate( 호출 구간에 strategy_code 를 strategy_id fallback 으로 쓰지 않음
    assert "else (\n                            command.strategy_code" not in src
    assert "order_source=str(command.order_source or" in src
    assert "strategy_id=command.strategy_id" in src
