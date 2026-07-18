from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.broker.factory import BrokerAdapterFactory
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.order.models import OrderStatus
from stock_platform.position.exit_monitor import (
    ManagedPosition,
    PositionExitMonitorService,
)
from stock_platform.position.lot_rounding import (
    round_share_quantity,
    round_price_to_tick,
)
from stock_platform.risk.engine import RiskManagementEngine
from stock_platform.risk.models import (
    PositionSizingMode,
    PositionSizingRequest,
    RiskPolicy,
)
from stock_platform.risk_engine.models import (
    RiskAccountState,
    RiskDecisionLevel,
    RiskOrderRequest,
    RiskOrderSide,
    RiskPolicy as EngineRiskPolicy,
)
from stock_platform.risk_engine.rules import (
    BrokerHealthRule,
    MarketDataFreshnessRule,
)
from stock_platform.trading.execution_sync_service import (
    ExecutionSyncService,
)


def test_krx_lot_and_tick_rounding() -> None:
    assert round_share_quantity(Decimal("1.9")) == Decimal("1")
    assert round_price_to_tick(Decimal("75321")) == Decimal("75300")


def test_risk_based_uses_stop_distance() -> None:
    engine = RiskManagementEngine()
    policy = RiskPolicy(
        position_sizing_mode=PositionSizingMode.RISK_BASED,
        risk_per_trade_ratio=Decimal("0.01"),
        stop_loss_ratio=Decimal("0.05"),
        take_profit_ratio=Decimal("0.10"),
        maximum_position_ratio=Decimal("0.5"),
        maximum_positions=5,
        minimum_order_amount=Decimal("1000"),
        maximum_total_invested_ratio=Decimal("0.8"),
    )
    plan = engine.create_position_plan(
        PositionSizingRequest(
            portfolio_value=Decimal("10000000"),
            available_cash=Decimal("5000000"),
            current_price=Decimal("10000"),
            current_position_count=0,
            policy=policy,
            stop_price=Decimal("9000"),
            invested_amount=Decimal("0"),
            apply_krx_lot_rounding=True,
        )
    )
    assert plan.approved is True
    # risk_budget=100000, risk/share=1000 => qty=100
    assert plan.quantity == Decimal("100")
    assert plan.stop_loss_price == Decimal("9000")


def test_market_data_freshness_blocks_stale() -> None:
    result = MarketDataFreshnessRule().evaluate(
        order=RiskOrderRequest(
            exchange_code="KRX",
            symbol="005930",
            side=RiskOrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("70000"),
            account_id=1,
            requested_at=datetime.now(timezone.utc),
            market_data_age_seconds=120,
        ),
        account=RiskAccountState(
            cash_balance=Decimal("1000000"),
            total_asset_value=Decimal("1000000"),
            invested_amount=Decimal("0"),
            daily_realized_profit_loss=Decimal("0"),
            daily_unrealized_profit_loss=Decimal("0"),
            open_position_count=0,
        ),
        policy=EngineRiskPolicy(
            max_market_data_age_seconds=30,
        ),
    )
    assert result.level == RiskDecisionLevel.BLOCK


def test_broker_health_blocks_high_error_rate() -> None:
    result = BrokerHealthRule().evaluate(
        order=RiskOrderRequest(
            exchange_code="KRX",
            symbol="005930",
            side=RiskOrderSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("70000"),
            account_id=1,
            requested_at=datetime.now(timezone.utc),
            broker_error_rate=Decimal("0.9"),
        ),
        account=RiskAccountState(
            cash_balance=Decimal("1000000"),
            total_asset_value=Decimal("1000000"),
            invested_amount=Decimal("0"),
            daily_realized_profit_loss=Decimal("0"),
            daily_unrealized_profit_loss=Decimal("0"),
            open_position_count=0,
        ),
        policy=EngineRiskPolicy(
            max_broker_error_rate=Decimal("0.5"),
        ),
    )
    assert result.level == RiskDecisionLevel.BLOCK


def test_live_adapter_requires_flag(monkeypatch) -> None:
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        BrokerAdapterFactory.create(
            BrokerEnvironment.LIVE,
            "KIWOOM",
            session=object(),
        )
        raised = False
    except PermissionError:
        raised = True
    finally:
        get_settings.cache_clear()
    assert raised is True


def test_execution_sync_normalizes_pending_to_fill() -> None:
    service = ExecutionSyncService.__new__(ExecutionSyncService)
    order = SimpleNamespace(
        order_id=1,
        status_code=OrderStatus.PENDING.value,
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("10"),
        order_quantity=Decimal("10"),
        average_fill_price=None,
        filled_amount=Decimal("0"),
    )
    orders = MagicMock()
    orders.get_by_broker_order_id.return_value = order

    def change_status(*, entity, new_status, **kwargs):
        entity.status_code = new_status.value
        return entity

    orders.change_status.side_effect = change_status
    executions = MagicMock()
    executions.exists.return_value = False
    executions.create.return_value = SimpleNamespace(
        execution_id=99
    )
    service._orders = orders
    service._executions = executions
    service._session = MagicMock()

    from stock_platform.broker.kiwoom.execution_models import (
        KiwoomExecutionEvent,
    )

    result = service.synchronize(
        KiwoomExecutionEvent(
            broker_order_id="B1",
            broker_execution_id="E1",
            symbol="005930",
            side_code="BUY",
            execution_quantity=Decimal("10"),
            execution_price=Decimal("70000"),
            remaining_quantity=Decimal("0"),
            executed_at=datetime.now(timezone.utc),
            raw_payload={},
        )
    )
    assert result.duplicate is False
    assert result.order_status == OrderStatus.FILLED.value
    assert order.status_code == OrderStatus.FILLED.value


def test_exit_monitor_submits_stop_loss(monkeypatch) -> None:
    monitor = PositionExitMonitorService.__new__(
        PositionExitMonitorService
    )
    monitor._risk_engine = RiskManagementEngine()
    fake_execution = MagicMock()
    fake_execution.submit.return_value = SimpleNamespace(
        allowed=True,
        order_id=42,
    )
    monitor._execution = fake_execution

    actions = monitor.evaluate_and_exit(
        [
            ManagedPosition(
                account_id=1,
                exchange_code="KRX",
                symbol="005930",
                quantity=Decimal("2"),
                entry_price=Decimal("70000"),
                current_price=Decimal("65000"),
                highest_price=Decimal("72000"),
                stop_loss_price=Decimal("66000"),
                take_profit_price=Decimal("80000"),
            )
        ],
        skip_risk_checks=True,
    )
    assert actions[0].submitted is True
    assert actions[0].reason == "STOP_LOSS"
    fake_execution.submit.assert_called_once()
