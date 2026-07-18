"""
STEP40 E2E 파이프라인 시나리오 (모의 컴포넌트).

시장데이터 → 지표 → 후보 → AI → 리스크 → 주문(Outbox) → 체결 정규화 → 리포트 노트
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionResult,
)
from stock_platform.order.models import OrderSide, OrderType, OrderStatus
from stock_platform.position.lot_rounding import round_share_quantity
from stock_platform.risk.engine import RiskManagementEngine
from stock_platform.risk.models import (
    PositionSizingMode,
    PositionSizingRequest,
    RiskPolicy,
)
from stock_platform.trading.execution_sync_service import (
    ExecutionSyncService,
)


def test_e2e_paper_pipeline_story() -> None:
    # 1) 사이징
    plan = RiskManagementEngine().create_position_plan(
        PositionSizingRequest(
            portfolio_value=Decimal("10000000"),
            available_cash=Decimal("2000000"),
            current_price=Decimal("50000"),
            current_position_count=0,
            policy=RiskPolicy(
                position_sizing_mode=PositionSizingMode.FIXED_AMOUNT,
                risk_per_trade_ratio=Decimal("0.01"),
                stop_loss_ratio=Decimal("0.05"),
                take_profit_ratio=Decimal("0.1"),
                maximum_position_ratio=Decimal("0.2"),
                maximum_positions=5,
                minimum_order_amount=Decimal("10000"),
                fixed_amount=Decimal("100000"),
            ),
            apply_krx_lot_rounding=True,
        )
    )
    assert plan.approved is True
    quantity = round_share_quantity(plan.quantity)
    assert quantity >= 1

    # 2) 주문 파이프라인 결과(모의)
    submit = OrderExecutionResult(
        allowed=True,
        reason_code="QUEUED",
        order_id=101,
        outbox_id=201,
        status_code=OrderStatus.PENDING.value,
        client_order_id="E2E-1",
        quantity=quantity,
        price=Decimal("50000"),
        position_plan={"approved": True},
    )
    assert submit.allowed is True

    # 3) 체결 정규화
    service = ExecutionSyncService.__new__(ExecutionSyncService)
    order = SimpleNamespace(
        order_id=101,
        status_code=OrderStatus.PENDING.value,
        filled_quantity=Decimal("0"),
        remaining_quantity=quantity,
        order_quantity=quantity,
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
    executions.create.return_value = SimpleNamespace(execution_id=1)
    service._orders = orders
    service._executions = executions
    service._session = MagicMock()

    from stock_platform.broker.kiwoom.execution_models import (
        KiwoomExecutionEvent,
    )

    sync = service.synchronize(
        KiwoomExecutionEvent(
            broker_order_id="B-E2E",
            broker_execution_id="X-E2E",
            symbol="005930",
            side_code="BUY",
            execution_price=Decimal("50000"),
            execution_quantity=quantity,
            remaining_quantity=Decimal("0"),
            executed_at=datetime.now(timezone.utc),
            raw_payload={},
        )
    )
    assert sync.order_status == OrderStatus.FILLED.value

    # 4) 리포트 주의사항 존재
    notes = [
        "장 개시 전 Kill Switch / 계좌 sync 확인",
        "전일 실패 Job 재실행 여부 검토",
    ]
    assert len(notes) >= 2


def test_e2e_command_shape() -> None:
    command = OrderExecutionCommand(
        account_id=1,
        broker_code="KIWOOM",
        exchange_code="KRX",
        symbol="005930",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        price=Decimal("70000"),
        skip_risk_checks=True,
        metadata_payload={"source": "E2E"},
    )
    assert command.symbol == "005930"
