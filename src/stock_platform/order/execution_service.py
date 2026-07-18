from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.order.id_generator import ClientOrderIdGenerator
from stock_platform.order.models import (
    CreateOrderCommand,
    OrderSide,
    OrderStatus,
    OrderTimeInForce,
    OrderType,
)
from stock_platform.order.outbox_models import OutboxEventType
from stock_platform.order.outbox_repository import OrderOutboxRepository
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.order.service import TradingOrderService
from stock_platform.risk.engine import RiskManagementEngine
from stock_platform.risk.models import (
    PositionSizingMode,
    PositionSizingRequest,
    RiskPolicy,
)
from stock_platform.risk_engine.kill_switch_guard import (
    PersistentKillSwitchGuard,
)
from stock_platform.risk_engine.order_guard import (
    DatabaseBackedRiskOrderGuard,
)


@dataclass(frozen=True, slots=True)
class OrderExecutionCommand:
    """단일 주문 진입점 입력."""

    account_id: int
    broker_code: str
    exchange_code: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: Decimal | None
    quantity: Decimal | None = None
    order_amount: Decimal | None = None
    time_in_force: OrderTimeInForce = OrderTimeInForce.DAY
    strategy_code: str | None = None
    strategy_deployment_id: int | None = None
    portfolio_id: int | None = None
    position_id: int | None = None
    client_order_id: str | None = None
    idempotency_key: str | None = None
    account_number: str | None = None
    portfolio_value: Decimal | None = None
    available_cash: Decimal | None = None
    current_position_count: int = 0
    skip_risk_checks: bool = False
    metadata_payload: dict[str, Any] | None = None
    actor: str = "ORDER_EXECUTION"


@dataclass(frozen=True, slots=True)
class OrderExecutionResult:
    allowed: bool
    reason_code: str
    order_id: int | None
    outbox_id: int | None
    status_code: str | None
    client_order_id: str | None
    quantity: Decimal | None
    price: Decimal | None
    position_plan: dict[str, Any] | None = None


class OrderExecutionService:
    """
    Signal → Position Sizing → Risk → Safety/KillSwitch
    → Idempotency/Outbox → Order State 단일 진입점.

    Broker 직접 호출은 하지 않으며 Outbox Worker만 송신한다.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._order_service = TradingOrderService(session)
        self._order_repository = TradingOrderRepository(session)
        self._outbox_repository = OrderOutboxRepository(session)
        self._sizing_engine = RiskManagementEngine()

    def submit(
        self,
        command: OrderExecutionCommand,
    ) -> OrderExecutionResult:
        account_number = (
            command.account_number
            or get_settings().kiwoom_account_number.strip()
        )
        if not account_number and not command.skip_risk_checks:
            return self._blocked(
                "RISK_ACCOUNT_NUMBER_MISSING"
            )

        try:
            quantity, price, plan_payload = self._resolve_size(
                command
            )
        except ValueError as exc:
            return self._blocked(
                "POSITION_SIZING_REJECTED",
                message=str(exc),
            )

        if not command.skip_risk_checks:
            try:
                PersistentKillSwitchGuard(
                    self._session
                ).require_order_allowed(
                    side=command.side.value,
                    allow_sell=True,
                )
            except PermissionError:
                return self._blocked(
                    "GLOBAL_KILL_SWITCH_ACTIVE"
                )

            risk_result = DatabaseBackedRiskOrderGuard(
                self._session,
                broker_code=command.broker_code,
            ).check(
                account_number=account_number,
                account_id=command.account_id,
                exchange_code=command.exchange_code,
                symbol=command.symbol,
                side=command.side.value,
                quantity=quantity,
                price=price,
            )
            if not risk_result.allowed:
                return self._blocked(
                    risk_result.blocked_reason
                    or "RISK_ENGINE_BLOCKED",
                )

        client_order_id = (
            command.client_order_id
            or ClientOrderIdGenerator.generate()
        )
        idempotency_key = (
            command.idempotency_key
            or f"SUBMIT:{client_order_id}"
        )

        existing_outbox = (
            self._outbox_repository.get_by_idempotency_key(
                idempotency_key
            )
        )
        if existing_outbox is not None:
            existing_order = self._order_repository.get(
                existing_outbox.order_id
            )
            return OrderExecutionResult(
                allowed=True,
                reason_code="IDEMPOTENT_REPLAY",
                order_id=existing_outbox.order_id,
                outbox_id=existing_outbox.outbox_id,
                status_code=(
                    existing_order.status_code
                    if existing_order
                    else None
                ),
                client_order_id=(
                    existing_order.client_order_id
                    if existing_order
                    else client_order_id
                ),
                quantity=(
                    existing_order.order_quantity
                    if existing_order
                    else quantity
                ),
                price=(
                    existing_order.order_price
                    if existing_order
                    else price
                ),
                position_plan=plan_payload,
            )

        metadata = dict(command.metadata_payload or {})
        metadata.setdefault("pipeline", "ORDER_EXECUTION_V1")
        if plan_payload:
            metadata["position_plan"] = plan_payload

        order = self._order_service.create(
            CreateOrderCommand(
                account_id=command.account_id,
                broker_code=command.broker_code,
                exchange_code=command.exchange_code,
                symbol=command.symbol,
                side=command.side,
                order_type=command.order_type,
                quantity=quantity,
                price=price,
                time_in_force=command.time_in_force,
                strategy_code=command.strategy_code,
                strategy_deployment_id=(
                    command.strategy_deployment_id
                ),
                portfolio_id=command.portfolio_id,
                position_id=command.position_id,
                client_order_id=client_order_id,
                metadata_payload=metadata,
            ),
            actor=command.actor,
        )

        order = self._order_repository.change_status(
            entity=order,
            new_status=OrderStatus.PENDING,
            actor=command.actor,
            reason_code="PIPELINE_QUEUED",
            message="Queued via OrderExecutionService",
            commit=False,
        )

        outbox = self._outbox_repository.enqueue(
            order_id=order.order_id,
            event_type=OutboxEventType.SUBMIT_ORDER,
            idempotency_key=idempotency_key,
            payload_json={
                "client_order_id": order.client_order_id,
                "account_id": order.account_id,
                "exchange_code": order.exchange_code,
                "symbol": order.symbol,
                "side": order.side_code,
                "order_type": order.order_type_code,
                "quantity": str(order.order_quantity),
                "price": (
                    None
                    if order.order_price is None
                    else str(order.order_price)
                ),
                "time_in_force": order.time_in_force_code,
            },
        )
        self._session.commit()
        self._session.refresh(order)

        return OrderExecutionResult(
            allowed=True,
            reason_code="QUEUED",
            order_id=order.order_id,
            outbox_id=outbox.outbox_id,
            status_code=order.status_code,
            client_order_id=order.client_order_id,
            quantity=order.order_quantity,
            price=order.order_price,
            position_plan=plan_payload,
        )

    def enqueue_existing(
        self,
        *,
        order_id: int,
        actor: str = "ORDER_DISPATCHER",
        idempotency_key: str | None = None,
    ) -> OrderExecutionResult:
        """기존 CREATED 주문을 Outbox에 넣고 PENDING으로 전이한다."""
        order = self._order_repository.get(order_id)
        if order is None:
            raise LookupError("Order not found")

        status = OrderStatus(order.status_code)
        if status == OrderStatus.CREATED:
            order = self._order_repository.change_status(
                entity=order,
                new_status=OrderStatus.PENDING,
                actor=actor,
                reason_code="DISPATCH_REQUESTED",
                commit=False,
            )
        elif status != OrderStatus.PENDING:
            raise ValueError(
                f"Order status not dispatchable: {status.value}"
            )

        key = (
            idempotency_key
            or f"SUBMIT:{order.client_order_id}"
        )
        outbox = self._outbox_repository.enqueue(
            order_id=order.order_id,
            event_type=OutboxEventType.SUBMIT_ORDER,
            idempotency_key=key,
            payload_json={
                "client_order_id": order.client_order_id,
                "account_id": order.account_id,
                "exchange_code": order.exchange_code,
                "symbol": order.symbol,
                "side": order.side_code,
                "order_type": order.order_type_code,
                "quantity": str(order.order_quantity),
                "price": (
                    None
                    if order.order_price is None
                    else str(order.order_price)
                ),
                "time_in_force": order.time_in_force_code,
            },
        )
        self._session.commit()
        self._session.refresh(order)
        return OrderExecutionResult(
            allowed=True,
            reason_code="QUEUED",
            order_id=order.order_id,
            outbox_id=outbox.outbox_id,
            status_code=order.status_code,
            client_order_id=order.client_order_id,
            quantity=order.order_quantity,
            price=order.order_price,
        )

    def _resolve_size(
        self,
        command: OrderExecutionCommand,
    ) -> tuple[Decimal, Decimal, dict[str, Any] | None]:
        if command.order_type == OrderType.LIMIT:
            if command.price is None or command.price <= 0:
                raise ValueError("LIMIT order requires price > 0")
            price = command.price
        else:
            if command.price is None or command.price <= 0:
                raise ValueError(
                    "MARKET order requires reference price for sizing"
                )
            price = command.price

        if command.quantity is not None:
            if command.quantity <= 0:
                raise ValueError("quantity must be greater than zero")
            return command.quantity, price, None

        if command.order_amount is None or command.order_amount <= 0:
            raise ValueError(
                "quantity or order_amount is required"
            )

        portfolio_value = (
            command.portfolio_value
            or command.order_amount
        )
        available_cash = (
            command.available_cash
            or command.order_amount
        )
        policy = RiskPolicy(
            position_sizing_mode=PositionSizingMode.FIXED_AMOUNT,
            risk_per_trade_ratio=Decimal("0.01"),
            stop_loss_ratio=Decimal("0.05"),
            take_profit_ratio=Decimal("0.10"),
            maximum_position_ratio=Decimal("1"),
            maximum_positions=100,
            minimum_order_amount=Decimal("1"),
            fixed_amount=command.order_amount,
        )
        plan = self._sizing_engine.create_position_plan(
            PositionSizingRequest(
                portfolio_value=portfolio_value,
                available_cash=available_cash,
                current_price=price,
                current_position_count=(
                    command.current_position_count
                ),
                policy=policy,
            )
        )
        if not plan.approved:
            raise ValueError(plan.reason)

        return (
            plan.quantity,
            price,
            {
                "approved": plan.approved,
                "reason": plan.reason,
                "quantity": str(plan.quantity),
                "order_amount": str(plan.order_amount),
                "stop_loss_price": str(plan.stop_loss_price),
                "take_profit_price": str(
                    plan.take_profit_price
                ),
            },
        )

    @staticmethod
    def _blocked(
        reason_code: str,
        *,
        message: str | None = None,
    ) -> OrderExecutionResult:
        return OrderExecutionResult(
            allowed=False,
            reason_code=reason_code,
            order_id=None,
            outbox_id=None,
            status_code=None,
            client_order_id=None,
            quantity=None,
            price=None,
            position_plan=(
                {"message": message}
                if message
                else None
            ),
        )
