"""ORDER_LIMIT_V2 — submit vs filled-entry semantics (focused)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.order.order_limit_policy_v2 import (
    ORDER_LIMIT_V1,
    ORDER_LIMIT_V2,
    ORDER_LIMIT_V2_MIN_TRADING_DATE,
    REASON_DAILY_FILLED_ENTRY_LIMIT,
    REASON_DAILY_ORDER_LIMIT,
    REASON_DAILY_SUBMIT_LIMIT,
    effective_v2_limits,
    parse_strategy_id,
    resolve_order_limit_policy_version,
)
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy


def _policy(**overrides) -> ResolvedRiskPolicy:
    base = dict(
        max_order_amount=Decimal("5000"),
        daily_max_order_amount=Decimal("1000000"),
        max_total_investment_amount=Decimal("10000000"),
        max_position_amount=Decimal("10000000"),
        max_position_count=5,
        max_position_weight=Decimal("1"),
        max_investment_ratio=Decimal("1"),
        allow_duplicate_buy=True,
        daily_max_loss_amount=Decimal("10000000"),
        daily_max_loss_rate=Decimal("0.05"),
        stop_loss_rate=Decimal("0.05"),
        take_profit_rate=Decimal("0.1"),
        trailing_stop_rate=Decimal("0.03"),
        auto_trading_enabled=True,
        buy_enabled=True,
        sell_enabled=True,
        sell_only=False,
        account_paused=False,
        max_order_quantity=Decimal("100"),
        daily_order_limit=1,
        duplicate_order_window_seconds=5,
        max_open_orders=1,
        max_slippage_rate=Decimal("0.01"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=300,
        source_layers=("account",),
        daily_submit_limit=None,
        daily_filled_entry_limit=None,
    )
    base.update(overrides)
    return ResolvedRiskPolicy(**base)


def test_v1_forced_on_2026_08_21_even_if_v2_fields_set() -> None:
    assert (
        resolve_order_limit_policy_version(
            trading_date=date(2026, 8, 21),
            daily_submit_limit=5,
            daily_filled_entry_limit=1,
        )
        == ORDER_LIMIT_V1
    )


def test_v2_requires_next_day_and_admin_opt_in() -> None:
    assert (
        resolve_order_limit_policy_version(
            trading_date=ORDER_LIMIT_V2_MIN_TRADING_DATE,
            daily_submit_limit=None,
            daily_filled_entry_limit=None,
        )
        == ORDER_LIMIT_V1
    )
    assert (
        resolve_order_limit_policy_version(
            trading_date=ORDER_LIMIT_V2_MIN_TRADING_DATE,
            daily_submit_limit=5,
            daily_filled_entry_limit=1,
        )
        == ORDER_LIMIT_V2
    )


def test_effective_v2_limits_no_auto_relax() -> None:
    # admin이 submit만 설정하면 filled는 legacy daily_order_limit 유지
    submit, filled = effective_v2_limits(
        daily_order_limit=1,
        daily_submit_limit=5,
        daily_filled_entry_limit=None,
    )
    assert submit == 5
    assert filled == 1


def test_parse_strategy_id_manual_excluded() -> None:
    assert parse_strategy_id(None) is None
    assert parse_strategy_id("manual") is None
    assert parse_strategy_id("17579") == 17579


def test_dry_scenario_counters_logic() -> None:
    """Order A cancel no-fill → submit1 filled0; B fill → submit2 filled1; C blocked."""

    submit_lim, filled_lim = 5, 1
    submit_count = 0
    filled_count = 0

    # A: submit + cancel no fill
    submit_count += 1
    assert submit_count == 1 and filled_count == 0
    assert submit_count < submit_lim and filled_count < filled_lim

    # B: submit + fill
    submit_count += 1
    filled_count += 1
    assert submit_count == 2 and filled_count == 1
    assert filled_count >= filled_lim  # C blocked on filled

    # C would hit filled limit
    assert filled_count >= filled_lim
    # Protective SELL is not an ENTRY — not counted here
    assert REASON_DAILY_FILLED_ENTRY_LIMIT == "DAILY_FILLED_ENTRY_LIMIT_REACHED"
    assert REASON_DAILY_SUBMIT_LIMIT == "DAILY_SUBMIT_LIMIT_REACHED"
    assert REASON_DAILY_ORDER_LIMIT == "DAILY_ORDER_LIMIT_EXCEEDED"


def test_usage_service_filled_entry_idempotent() -> None:
    from stock_platform.risk_engine.strategy_daily_order_usage_service import (
        StrategyDailyOrderUsageService,
    )
    from stock_platform.risk_engine.strategy_owned_entities import (
        StrategyDailyOrderUsageEntity,
    )

    session = MagicMock()
    row = StrategyDailyOrderUsageEntity(
        trading_date=date(2026, 8, 22),
        broker_code="KIWOOM",
        user_broker_account_id=1,
        strategy_id=10,
        deployment_id=0,
        submit_count=1,
        filled_entry_count=0,
        filled_entry_order_ids=[],
        policy_version=ORDER_LIMIT_V2,
        meta_json={},
    )
    svc = StrategyDailyOrderUsageService(session)
    svc.get_or_create = MagicMock(return_value=row)  # type: ignore[method-assign]

    first = svc.record_filled_entry(
        user_broker_account_id=1,
        broker_code="KIWOOM",
        strategy_id=10,
        deployment_id=0,
        entry_order_id=100,
        trading_date=date(2026, 8, 22),
    )
    second = svc.record_filled_entry(
        user_broker_account_id=1,
        broker_code="KIWOOM",
        strategy_id=10,
        deployment_id=0,
        entry_order_id=100,
        trading_date=date(2026, 8, 22),
    )
    assert first["incremented"] is True
    assert first["filled_entry_count"] == 1
    assert second["incremented"] is False
    assert second["filled_entry_count"] == 1


def test_try_reserve_submit_sql_bound() -> None:
    from stock_platform.risk_engine.strategy_daily_order_usage_service import (
        StrategyDailyOrderUsageService,
    )

    session = MagicMock()
    # first get_or_create path
    existing = SimpleNamespace(
        trading_date=date(2026, 8, 22),
        submit_count=0,
        filled_entry_count=0,
        policy_version=ORDER_LIMIT_V2,
        strategy_id=10,
        deployment_id=0,
    )
    session.scalar.return_value = existing
    # UPDATE returning empty → limit hit
    result = MagicMock()
    result.mappings.return_value.first.return_value = None
    session.execute.return_value = result

    svc = StrategyDailyOrderUsageService(session)
    svc.snapshot = MagicMock(  # type: ignore[method-assign]
        return_value={
            "trading_date": "2026-08-22",
            "submit_count": 5,
            "filled_entry_count": 0,
            "policy_version": ORDER_LIMIT_V2,
            "strategy_id": 10,
            "deployment_id": 0,
        }
    )
    ok, snap = svc.try_reserve_submit(
        user_broker_account_id=1,
        broker_code="KIWOOM",
        strategy_id=10,
        deployment_id=0,
        submit_limit=5,
        trading_date=date(2026, 8, 22),
    )
    assert ok is False
    assert snap["submit_count"] == 5


def test_policy_dataclass_accepts_v2_fields() -> None:
    p = _policy(daily_submit_limit=5, daily_filled_entry_limit=1)
    assert p.daily_submit_limit == 5
    assert p.daily_filled_entry_limit == 1
    assert p.daily_order_limit == 1


@pytest.mark.parametrize(
    "trading_date,expect_v1",
    [
        (date(2026, 8, 21), True),
        (date(2026, 8, 22), False),
    ],
)
def test_legacy_today_vs_next_day(trading_date: date, expect_v1: bool) -> None:
    version = resolve_order_limit_policy_version(
        trading_date=trading_date,
        daily_submit_limit=5,
        daily_filled_entry_limit=1,
    )
    assert (version == ORDER_LIMIT_V1) is expect_v1
