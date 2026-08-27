"""UPBIT LIVE Position Exit Monitor — fixture/mock only.

실 UPBIT API · LIVE Activation/ARM/Worker/주문 금지.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.models import OrderSide
from stock_platform.position.exit_monitor import (
    ManagedPosition,
    PositionExitMonitorService,
)
from stock_platform.position.exit_monitor_live import (
    has_blocking_live_exit_sell,
    persist_high_water,
    read_persisted_high_water,
    resolve_trailing_high_water,
)
from stock_platform.realtime.ai_signal_gate_exit_policy import (
    should_bypass_ai_gate,
)


ZERO = Decimal("0")
UBA1380 = 1380
UBA_OTHER = 1381


def _open_binding(binding_id: int = 42) -> SimpleNamespace:
    return SimpleNamespace(
        binding_id=binding_id,
        strategy_id=1,
        status="OPEN",
        owned_quantity=Decimal("100"),
    )


@pytest.fixture(autouse=True)
def _patch_live_exit_open_binding_gate():
    """LIVE exit OPEN-binding gate — 단위테스트 기본 mock."""

    with (
        patch(
            "stock_platform.position.exit_monitor_live.load_open_strategy_binding",
            return_value=_open_binding(),
        ),
        patch(
            "stock_platform.position.exit_monitor_live.load_broker_position_snapshot",
            return_value=None,
        ),
    ):
        yield


def _live_pos(**overrides) -> ManagedPosition:
    base = dict(
        account_id=0,
        exchange_code="UPBIT",
        symbol="KRW-XRP",
        quantity=Decimal("100"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        highest_price=Decimal("100"),
        stop_loss_price=Decimal("95"),
        take_profit_price=Decimal("110"),
        trailing_stop_ratio=Decimal("0.03"),
        relative_loss_ratio=None,
        broker_code="UPBIT",
        user_broker_account_id=UBA1380,
        owner_user_id=61,
        environment="LIVE",
    )
    base.update(overrides)
    return ManagedPosition(**base)


def _monitor(session=None, *, allowed=True, order_id=501, reason="OK"):
    session = session or MagicMock()
    monitor = PositionExitMonitorService(session)
    fake = MagicMock()
    fake.submit.return_value = SimpleNamespace(
        allowed=allowed,
        order_id=order_id if allowed else None,
        reason_code=reason,
        outbox_id=7 if allowed else None,
    )
    monitor._execution = fake
    return monitor, fake


def test_ai_gate_trailing_stop_bypass() -> None:
    signal = SimpleNamespace(action="SELL", reason_code="TRAILING_STOP")
    bypass, code = should_bypass_ai_gate(signal)
    assert bypass is True
    assert code == "AI_GATE_BYPASS_TRAILING_STOP"


def test_stop_loss_queues_exactly_one_sell() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    monitor, execution = _monitor(session)
    with patch(
        "stock_platform.position.exit_monitor_live.load_pending_sell_quantity",
        return_value=ZERO,
    ):
        actions = monitor.evaluate_and_exit(
            [_live_pos(current_price=Decimal("94"))],
            skip_risk_checks=False,
        )
    assert actions[0].reason == "STOP_LOSS"
    assert actions[0].submitted is True
    execution.submit.assert_called_once()
    cmd = execution.submit.call_args.args[0]
    assert cmd.side == OrderSide.SELL
    assert cmd.environment == "LIVE"
    assert cmd.user_broker_account_id == UBA1380
    assert cmd.account_id is None
    assert cmd.order_source == "EXIT"
    assert cmd.broker_code == "UPBIT"


def test_take_profit_queues_exactly_one_sell() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    monitor, execution = _monitor(session)
    with patch(
        "stock_platform.position.exit_monitor_live.load_pending_sell_quantity",
        return_value=ZERO,
    ):
        actions = monitor.evaluate_and_exit(
            [_live_pos(current_price=Decimal("111"))],
            skip_risk_checks=False,
        )
    assert actions[0].reason == "TAKE_PROFIT"
    assert actions[0].submitted is True
    execution.submit.assert_called_once()


def test_trailing_stop_queues_when_high_water_persisted() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    monitor, execution = _monitor(session)
    with patch(
        "stock_platform.position.exit_monitor_live.load_pending_sell_quantity",
        return_value=ZERO,
    ):
        actions = monitor.evaluate_and_exit(
            [
                _live_pos(
                    current_price=Decimal("116"),
                    highest_price=Decimal("120"),
                    stop_loss_price=Decimal("50"),
                    take_profit_price=Decimal("200"),
                )
            ],
            skip_risk_checks=False,
        )
    assert actions[0].reason == "TRAILING_STOP"
    assert actions[0].submitted is True
    execution.submit.assert_called_once()


def test_trailing_not_fired_without_persisted_high_water() -> None:
    row = SimpleNamespace(raw_data={})
    highest, allow = resolve_trailing_high_water(
        row, entry=Decimal("100"), current_price=Decimal("116")
    )
    assert allow is False
    assert highest == Decimal("100")
    assert read_persisted_high_water(row.raw_data) == Decimal("116")


def test_trailing_restart_uses_persisted_high_water() -> None:
    row = SimpleNamespace(raw_data={})
    persist_high_water(row, high_water=Decimal("120"))
    highest, allow = resolve_trailing_high_water(
        row, entry=Decimal("100"), current_price=Decimal("116")
    )
    assert allow is True
    assert highest == Decimal("120")


def test_duplicate_tick_second_submit_zero() -> None:
    session = MagicMock()
    monitor, execution = _monitor(session)
    with patch(
        "stock_platform.position.exit_monitor_live.has_blocking_live_exit_sell",
        side_effect=[False, True],
    ):
        first = monitor.evaluate_and_exit(
            [_live_pos(current_price=Decimal("94"))],
            skip_risk_checks=False,
        )
        second = monitor.evaluate_and_exit(
            [_live_pos(current_price=Decimal("94"))],
            skip_risk_checks=False,
        )
    assert first[0].submitted is True
    assert second[0].submitted is False
    assert execution.submit.call_count == 1


def test_pending_full_sell_blocks_new_exit() -> None:
    session = MagicMock()
    monitor, execution = _monitor(session)
    with patch(
        "stock_platform.position.exit_monitor_live.has_blocking_live_exit_sell",
        return_value=True,
    ):
        actions = monitor.evaluate_and_exit(
            [_live_pos(current_price=Decimal("94"))],
            skip_risk_checks=False,
        )
    assert actions[0].submitted is False
    execution.submit.assert_not_called()


def test_has_blocking_pending_quantity() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.position.exit_monitor_live.load_pending_sell_quantity",
        return_value=Decimal("100"),
    ):
        assert (
            has_blocking_live_exit_sell(
                session,
                user_broker_account_id=UBA1380,
                symbol="KRW-XRP",
                snapshot_synchronized_at=datetime.now(timezone.utc),
            )
            is True
        )


def test_filled_exit_newer_than_snapshot_blocks_race() -> None:
    now = datetime.now(timezone.utc)
    order = SimpleNamespace(
        status_code="FILLED",
        metadata_payload={"source": "POSITION_EXIT_MONITOR"},
        created_at=now,
        remaining_quantity=ZERO,
    )
    session = MagicMock()
    session.scalars.return_value = [order]
    with patch(
        "stock_platform.position.exit_monitor_live.load_pending_sell_quantity",
        return_value=ZERO,
    ):
        blocked = has_blocking_live_exit_sell(
            session,
            user_broker_account_id=UBA1380,
            symbol="KRW-XRP",
            snapshot_synchronized_at=now - timedelta(minutes=5),
        )
    assert blocked is True


def test_live_safety_blocks_do_not_call_broker() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    codes = [
        "ACTIVATION_INACTIVE",
        "LIVE_ORDER_DISABLED",
        "LIVE_ARM_EXPIRED",
        "KILL_SWITCH_ACTIVE",
        "TRADING_PAUSED",
        "RECOVERY_NOT_READY",
    ]
    for code in codes:
        monitor, execution = _monitor(
            session, allowed=False, order_id=None, reason=code
        )
        with patch(
            "stock_platform.position.exit_monitor_live.load_pending_sell_quantity",
            return_value=ZERO,
        ):
            actions = monitor.evaluate_and_exit(
                [_live_pos(current_price=Decimal("94"))],
                skip_risk_checks=False,
            )
        assert actions[0].submitted is False
        cmd = execution.submit.call_args.args[0]
        assert cmd.side == OrderSide.SELL


def test_monitor_never_submits_buy() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    monitor, execution = _monitor(session)
    with patch(
        "stock_platform.position.exit_monitor_live.load_pending_sell_quantity",
        return_value=ZERO,
    ):
        monitor.evaluate_and_exit(
            [
                _live_pos(current_price=Decimal("94")),
                _live_pos(symbol="KRW-XXX", current_price=Decimal("111")),
            ],
            skip_risk_checks=False,
        )
    for call in execution.submit.call_args_list:
        assert call.args[0].side == OrderSide.SELL


def test_cross_uba_uses_own_account_only() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    monitor, execution = _monitor(session)
    with patch(
        "stock_platform.position.exit_monitor_live.load_pending_sell_quantity",
        return_value=ZERO,
    ):
        monitor.evaluate_and_exit(
            [
                _live_pos(
                    symbol="KRW-XRP",
                    current_price=Decimal("94"),
                    user_broker_account_id=UBA1380,
                ),
                _live_pos(
                    symbol="KRW-BTC",
                    current_price=Decimal("94"),
                    user_broker_account_id=UBA_OTHER,
                ),
            ],
            skip_risk_checks=False,
        )
    for call in execution.submit.call_args_list:
        cmd = call.args[0]
        if cmd.symbol == "KRW-XRP":
            assert cmd.user_broker_account_id == UBA1380
        if cmd.symbol == "KRW-BTC":
            assert cmd.user_broker_account_id == UBA_OTHER


def test_position_cap_fixture_still_submits_exit_not_buy() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    monitor, execution = _monitor(session)
    with patch(
        "stock_platform.position.exit_monitor_live.load_pending_sell_quantity",
        return_value=ZERO,
    ):
        actions = monitor.evaluate_and_exit(
            [_live_pos(quantity=Decimal("50"), current_price=Decimal("94"))],
            skip_risk_checks=False,
        )
    assert actions[0].submitted is True
    assert execution.submit.call_args.args[0].side == OrderSide.SELL


def test_paper_path_unchanged_no_live_arm() -> None:
    from tests.test_position_exit_monitor_step53 import (
        _monitor_with_execution,
        _position,
    )

    monitor, execution = _monitor_with_execution()
    actions = monitor.evaluate_and_exit(
        [_position(current_price=Decimal("66000"))],
        skip_risk_checks=True,
    )
    assert actions[0].reason == "STOP_LOSS"
    cmd = execution.submit.call_args.args[0]
    assert getattr(cmd, "environment", "PAPER") != "LIVE"


def test_live_disabled_flag_loads_no_upbit_rows() -> None:
    from stock_platform.position.exit_monitor_loader import (
        PositionExitMonitorLoader,
    )

    session = MagicMock()
    session.scalars.return_value = []
    loader = PositionExitMonitorLoader(session)
    with (
        patch(
            "stock_platform.position.exit_monitor_loader.get_settings",
            return_value=SimpleNamespace(
                position_exit_monitor_live_upbit_enabled=False,
                position_exit_stop_loss_ratio=0.05,
                position_exit_take_profit_ratio=0.10,
                position_exit_trailing_stop_ratio=0.03,
                position_exit_relative_loss_ratio=None,
                scheduler_policy_id=1,
            ),
        ),
        patch(
            "stock_platform.position.exit_monitor_loader.KillSwitchService"
        ) as ks,
        patch(
            "stock_platform.position.exit_monitor_live.list_upbit_live_position_rows"
        ) as listing,
    ):
        ks.return_value.is_active.return_value = False
        ctx = loader.load()
    listing.assert_not_called()
    assert ctx.positions == []


def test_loader_skips_stale_price() -> None:
    from stock_platform.position.exit_monitor_loader import (
        PositionExitMonitorLoader,
    )

    uba = SimpleNamespace(
        user_broker_account_id=UBA1380,
        user_id=61,
        broker_code="UPBIT",
        is_active=True,
    )
    row = SimpleNamespace(
        symbol="KRW-XRP",
        exchange_code="UPBIT",
        quantity=Decimal("10"),
        average_purchase_price=Decimal("100"),
        raw_data={"exit_monitor_high_water": "120"},
        synchronized_at=datetime.now(timezone.utc),
    )
    session = MagicMock()
    session.scalars.return_value = []
    loader = PositionExitMonitorLoader(session)
    settings = SimpleNamespace(
        position_exit_monitor_live_upbit_enabled=True,
        autotrading_market_feed_stale_seconds=30,
        position_exit_stop_loss_ratio=0.05,
        position_exit_take_profit_ratio=0.10,
        position_exit_trailing_stop_ratio=0.03,
        position_exit_relative_loss_ratio=None,
        scheduler_policy_id=1,
    )
    with (
        patch(
            "stock_platform.position.exit_monitor_loader.get_settings",
            return_value=settings,
        ),
        patch(
            "stock_platform.position.exit_monitor_loader.KillSwitchService"
        ) as ks,
        patch(
            "stock_platform.position.exit_monitor_live.list_upbit_live_position_rows",
            return_value=[(row, uba)],
        ),
        patch(
            "stock_platform.position.exit_monitor_live.resolve_upbit_live_price",
            return_value=None,
        ),
        patch(
            "stock_platform.broker.recovery_lock.RecoveryAccountLockService"
        ) as lock,
        patch(
            "stock_platform.operation.upbit_full_market.service.UpbitFullMarketAssignmentService"
        ) as fma_cls,
    ):
        ks.return_value.is_active.return_value = False
        lock.return_value.is_trading_paused.return_value = False
        fma_cls.return_value.status_dict.return_value = {
            "mode": "FULL_MARKET_PORTFOLIO",
        }
        fma_cls.return_value.is_strategy_owned_symbol.return_value = True
        ctx = loader.load()
    assert ctx.positions == []
    assert any("stale_or_missing" in s for s in ctx.skipped_symbols)


def test_loader_maps_upbit_live_position_with_resolved_policy() -> None:
    from stock_platform.position.exit_monitor_loader import (
        PositionExitMonitorLoader,
    )

    uba = SimpleNamespace(
        user_broker_account_id=UBA1380,
        user_id=61,
        broker_code="UPBIT",
        is_active=True,
    )
    row = SimpleNamespace(
        symbol="KRW-XRP",
        exchange_code="UPBIT",
        quantity=Decimal("10"),
        average_purchase_price=Decimal("100"),
        raw_data={"exit_monitor_high_water": "100"},
        synchronized_at=datetime.now(timezone.utc),
    )
    session = MagicMock()
    session.scalars.return_value = []
    loader = PositionExitMonitorLoader(session)
    settings = SimpleNamespace(
        position_exit_monitor_live_upbit_enabled=True,
        autotrading_market_feed_stale_seconds=30,
        position_exit_stop_loss_ratio=0.05,
        position_exit_take_profit_ratio=0.10,
        position_exit_trailing_stop_ratio=0.03,
        position_exit_relative_loss_ratio=None,
        scheduler_policy_id=1,
    )
    policy = SimpleNamespace(
        stop_loss_rate=Decimal("0.05"),
        take_profit_rate=Decimal("0.10"),
        trailing_stop_rate=Decimal("0.03"),
        daily_max_loss_amount=Decimal("30000"),
    )
    with (
        patch(
            "stock_platform.position.exit_monitor_loader.get_settings",
            return_value=settings,
        ),
        patch(
            "stock_platform.position.exit_monitor_loader.KillSwitchService"
        ) as ks,
        patch(
            "stock_platform.position.exit_monitor_live.list_upbit_live_position_rows",
            return_value=[(row, uba)],
        ),
        patch(
            "stock_platform.position.exit_monitor_live.resolve_upbit_live_price",
            return_value=Decimal("94"),
        ),
        patch(
            "stock_platform.broker.recovery_lock.RecoveryAccountLockService"
        ) as lock,
        patch(
            "stock_platform.risk_engine.resolved_policy.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.operation.upbit_full_market.service.UpbitFullMarketAssignmentService"
        ) as fma_cls,
        patch(
            "stock_platform.position.exit_monitor_live.has_blocking_live_exit_sell",
            return_value=False,
        ),
        patch(
            "stock_platform.position.exit_monitor_live.load_open_strategy_binding",
            return_value=_open_binding(),
        ),
    ):
        ks.return_value.is_active.return_value = False
        lock.return_value.is_trading_paused.return_value = False
        resolver.return_value.resolve.return_value = policy
        # FMA ownership 검사는 통합 경로에서 검증 — 여기서는 skip (fail-open)
        fma_cls.return_value.status_dict.side_effect = RuntimeError(
            "test_skip_fma"
        )
        ctx = loader.load()
    assert len(ctx.positions) == 1
    pos = ctx.positions[0]
    assert pos.environment == "LIVE"
    assert pos.user_broker_account_id == UBA1380
    assert pos.broker_code == "UPBIT"
    assert pos.stop_loss_price == Decimal("95.00000000")
    assert pos.current_price == Decimal("94")
    assert pos.binding_id == 42

def test_no_direct_broker_calls_in_exit_monitor_modules() -> None:
    from pathlib import Path

    root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "stock_platform"
        / "position"
    )
    forbidden = (
        "adapter.submit_order",
        "upbit.create_order",
        "broker.submit_order",
    )
    for name in (
        "exit_monitor.py",
        "exit_monitor_loader.py",
        "exit_monitor_live.py",
        "exit_monitor_runtime.py",
        "exit_monitor_scheduler.py",
    ):
        text = (root / name).read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"{name} contains {needle}"
