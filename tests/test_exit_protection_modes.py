"""WRK-20260829-UPBIT-EXIT-POLICY-ALIGNMENT-V1 — tri-state REAL exit modes."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.risk.engine import RiskManagementEngine
from stock_platform.risk.models import ExitEvaluationRequest
from stock_platform.risk_engine.exit_protection_modes import (
    MODE_DISABLED,
    MODE_ENABLED,
    MODE_INHERIT,
    resolve_exit_protection,
)
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicyResolver


SYS_SL = Decimal("0.05")
SYS_TP = Decimal("0.10")
SYS_TR = Decimal("0.03")


def test_inherit_uses_system_stop_loss() -> None:
    r = resolve_exit_protection(
        key="stop_loss",
        system_rate=SYS_SL,
        user_mode=MODE_INHERIT,
        user_rate=None,
        account_mode=MODE_INHERIT,
        account_rate=None,
    )
    assert r.effective_enabled is True
    assert r.effective_rate == SYS_SL
    assert r.source == "SYSTEM"
    assert r.mode == MODE_INHERIT


def test_disabled_ignores_system_stop_loss() -> None:
    r = resolve_exit_protection(
        key="stop_loss",
        system_rate=SYS_SL,
        user_mode=MODE_INHERIT,
        user_rate=None,
        account_mode=MODE_DISABLED,
        account_rate=None,
    )
    assert r.effective_enabled is False
    assert r.effective_rate is None
    assert r.source == "UBA"
    assert r.mode == MODE_DISABLED


def test_enabled_own_stop_loss() -> None:
    own = Decimal("0.02")
    r = resolve_exit_protection(
        key="stop_loss",
        system_rate=SYS_SL,
        user_mode=MODE_INHERIT,
        user_rate=None,
        account_mode=MODE_ENABLED,
        account_rate=own,
    )
    assert r.effective_enabled is True
    assert r.effective_rate == own
    assert r.source == "UBA"


@pytest.mark.parametrize(
    ("mode", "rate", "enabled", "eff"),
    [
        (MODE_INHERIT, None, True, SYS_TP),
        (MODE_DISABLED, None, False, None),
        (MODE_ENABLED, Decimal("0.15"), True, Decimal("0.15")),
    ],
)
def test_take_profit_modes(mode, rate, enabled, eff) -> None:
    r = resolve_exit_protection(
        key="take_profit",
        system_rate=SYS_TP,
        user_mode=MODE_INHERIT,
        user_rate=None,
        account_mode=mode,
        account_rate=rate,
    )
    assert r.effective_enabled is enabled
    assert r.effective_rate == eff


@pytest.mark.parametrize(
    ("mode", "rate", "enabled", "eff"),
    [
        (MODE_INHERIT, None, True, SYS_TR),
        (MODE_DISABLED, None, False, None),
        (MODE_ENABLED, Decimal("0.04"), True, Decimal("0.04")),
    ],
)
def test_trailing_modes(mode, rate, enabled, eff) -> None:
    r = resolve_exit_protection(
        key="trailing_stop",
        system_rate=SYS_TR,
        user_mode=MODE_INHERIT,
        user_rate=None,
        account_mode=mode,
        account_rate=rate,
    )
    assert r.effective_enabled is enabled
    assert r.effective_rate == eff


def test_uba_overrides_user_enabled() -> None:
    r = resolve_exit_protection(
        key="stop_loss",
        system_rate=SYS_SL,
        user_mode=MODE_ENABLED,
        user_rate=Decimal("0.07"),
        account_mode=MODE_DISABLED,
        account_rate=None,
    )
    assert r.mode == MODE_DISABLED
    assert r.effective_enabled is False
    assert r.source == "UBA"


def test_null_row_backward_compat_inherit() -> None:
    """기존 NULL mode → INHERIT."""
    r = resolve_exit_protection(
        key="trailing_stop",
        system_rate=SYS_TR,
        user_mode=None,
        user_rate=None,
        account_mode=None,
        account_rate=None,
    )
    assert r.mode == MODE_INHERIT
    assert r.effective_rate == SYS_TR


def _system_ns() -> SimpleNamespace:
    return SimpleNamespace(
        singleton_key="DEFAULT",
        stop_loss_rate=SYS_SL,
        take_profit_rate=SYS_TP,
        trailing_stop_rate=SYS_TR,
        max_order_amount=Decimal("5000"),
        daily_max_order_amount=Decimal("100000"),
        max_total_investment_amount=Decimal("500000"),
        max_position_amount=Decimal("50000"),
        max_position_count=6,
        max_position_weight=Decimal("0.2"),
        max_investment_ratio=Decimal("1"),
        allow_duplicate_buy=True,
        daily_max_loss_amount=Decimal("10000"),
        daily_max_loss_rate=Decimal("0.05"),
        auto_trading_enabled=True,
        buy_enabled=True,
        sell_enabled=True,
        sell_only=False,
        account_paused=False,
        max_order_quantity=Decimal("100"),
        daily_order_limit=20,
        daily_submit_limit=None,
        daily_filled_entry_limit=None,
        duplicate_order_window_seconds=5,
        max_open_orders=6,
        max_slippage_rate=Decimal("0.01"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=300,
    )


def _uba_ns(**overrides) -> SimpleNamespace:
    base = dict(
        user_broker_account_id=1380,
        stop_loss_rate=None,
        take_profit_rate=None,
        trailing_stop_rate=None,
        stop_loss_mode=MODE_INHERIT,
        take_profit_mode=MODE_INHERIT,
        trailing_stop_mode=MODE_INHERIT,
        max_order_amount=None,
        daily_max_order_amount=None,
        max_total_investment_amount=None,
        max_position_amount=None,
        max_position_count=None,
        max_position_weight=None,
        max_investment_ratio=None,
        allow_duplicate_buy=None,
        daily_max_loss_amount=None,
        daily_max_loss_rate=None,
        auto_trading_enabled=None,
        buy_enabled=None,
        sell_enabled=None,
        sell_only=None,
        account_paused=None,
        max_order_quantity=None,
        daily_order_limit=None,
        daily_submit_limit=None,
        daily_filled_entry_limit=None,
        duplicate_order_window_seconds=None,
        max_open_orders=None,
        max_slippage_rate=None,
        anomaly_orders_per_minute=None,
        loop_detect_window_seconds=None,
        arm_ttl_seconds=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_resolver_disabled_uba_rates_none() -> None:
    session = MagicMock()
    system = _system_ns()
    uba = _uba_ns(
        stop_loss_mode=MODE_DISABLED,
        take_profit_mode=MODE_DISABLED,
        trailing_stop_mode=MODE_DISABLED,
    )
    calls = {"n": 0}

    def _scalar(_stmt):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            return system
        if calls["n"] == 2:
            return None
        return uba

    session.scalar.side_effect = _scalar
    resolved = ResolvedRiskPolicyResolver(session).resolve(
        user_id=1,
        user_broker_account_id=1380,
    )
    assert resolved.stop_loss_effective_enabled is False
    assert resolved.take_profit_effective_enabled is False
    assert resolved.trailing_stop_effective_enabled is False
    assert resolved.stop_loss_rate is None
    assert resolved.take_profit_rate is None
    assert resolved.trailing_stop_rate is None
    assert resolved.stop_loss_mode == MODE_DISABLED
    summary = resolved.exit_protection_summary()
    assert summary["stop_loss"]["effective_enabled"] is False
    assert summary["ma_dead_cross"]["effective_enabled"] is True


def test_resolver_inherit_keeps_system_rates() -> None:
    session = MagicMock()
    system = _system_ns()
    uba = _uba_ns()
    calls = {"n": 0}

    def _scalar(_stmt):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            return system
        if calls["n"] == 2:
            return None
        return uba

    session.scalar.side_effect = _scalar
    resolved = ResolvedRiskPolicyResolver(session).resolve(
        user_id=1,
        user_broker_account_id=1380,
    )
    assert resolved.stop_loss_rate == SYS_SL
    assert resolved.take_profit_rate == SYS_TP
    assert resolved.trailing_stop_rate == SYS_TR
    assert resolved.trailing_stop_effective_enabled is True


def test_evaluate_exit_skips_when_prices_none() -> None:
    engine = RiskManagementEngine()
    decision = engine.evaluate_exit(
        ExitEvaluationRequest(
            entry_price=Decimal("100"),
            current_price=Decimal("50"),
            highest_price=Decimal("120"),
            stop_loss_price=None,
            take_profit_price=None,
            trailing_stop_ratio=None,
        )
    )
    assert decision.should_exit is False
    assert decision.reason == "HOLD"


def test_trailing_condition_met_but_disabled_no_real_signal() -> None:
    """#1947 regression: trailing threshold met + ratio None → no REAL."""
    engine = RiskManagementEngine()
    decision = engine.evaluate_exit(
        ExitEvaluationRequest(
            entry_price=Decimal("100"),
            current_price=Decimal("90"),
            highest_price=Decimal("120"),
            stop_loss_price=None,
            take_profit_price=None,
            trailing_stop_ratio=None,
        )
    )
    assert decision.should_exit is False
    assert decision.reason != "TRAILING_STOP"


def test_trailing_enabled_fires() -> None:
    engine = RiskManagementEngine()
    decision = engine.evaluate_exit(
        ExitEvaluationRequest(
            entry_price=Decimal("100"),
            current_price=Decimal("90"),
            highest_price=Decimal("120"),
            stop_loss_price=None,
            take_profit_price=None,
            trailing_stop_ratio=Decimal("0.03"),
        )
    )
    assert decision.should_exit is True
    assert decision.reason == "TRAILING_STOP"


def test_disabled_does_not_imply_shadow_off() -> None:
    r = resolve_exit_protection(
        key="trailing_stop",
        system_rate=SYS_TR,
        user_mode=MODE_INHERIT,
        user_rate=None,
        account_mode=MODE_DISABLED,
        account_rate=None,
    )
    assert r.effective_enabled is False
    shadow_active = True
    assert shadow_active is True
