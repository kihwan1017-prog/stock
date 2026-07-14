from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

from sqlalchemy.orm import Session

from stock_platform.trading.execution_service import (
    PaperExecutionService,
)
from stock_platform.trading.models import (
    OrderSide,
    OrderType,
)
from stock_platform.trading.repository import (
    PaperOrderRepository,
)
from stock_platform.trading.service import (
    PaperOrderService,
)
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
    RealtimeExecutionResult,
)
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)


ZERO = Decimal("0")


class RealtimePaperOrderExecutor:
    """
    실시간 전략 신호를 모의 주문으로 변환하고,
    필요 시 즉시 모의 체결 후 계좌에 반영한다.
    """

    def __init__(
        self,
        session: Session,
        config: RealtimeExecutionConfig,
    ) -> None:
        self._session = session
        self._config = config
        self._order_service = PaperOrderService(
            PaperOrderRepository(session)
        )
        self._execution_service = PaperExecutionService(
            session
        )

    def execute(
        self,
        signal: RealtimeSignal,
    ) -> RealtimeExecutionResult:
        if self._config.mode != RealtimeExecutionMode.PAPER:
            raise ValueError(
                "LIVE execution is not supported yet"
            )

        if signal.action == RealtimeSignalAction.HOLD:
            return self._skipped(
                signal=signal,
                reason_code="HOLD_SIGNAL",
            )

        if (
            signal.action == RealtimeSignalAction.BUY
            and not self._config.allow_buy
        ):
            return self._skipped(
                signal=signal,
                reason_code="BUY_DISABLED",
            )

        if (
            signal.action == RealtimeSignalAction.SELL
            and not self._config.allow_sell
        ):
            return self._skipped(
                signal=signal,
                reason_code="SELL_DISABLED",
            )

        quantity = self._calculate_quantity(signal)

        if quantity <= ZERO:
            return self._skipped(
                signal=signal,
                reason_code="ZERO_QUANTITY",
            )

        side = (
            OrderSide.BUY
            if signal.action == RealtimeSignalAction.BUY
            else OrderSide.SELL
        )

        order = self._order_service.create(
            exchange_code=signal.exchange_code,
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            price=None,
            position_plan_id=None,
            auto_accept=True,
        )

        trade_id = None
        order_status = order.status_code

        if self._config.auto_fill:
            execution = self._execution_service.apply_fill(
                account_id=self._config.account_id,
                order_id=order.order_id,
                fill_quantity=quantity,
                fill_price=signal.signal_price,
            )
            trade_id = execution.trade_id
            order_status = execution.order_status

        return RealtimeExecutionResult(
            exchange_code=signal.exchange_code,
            symbol=signal.symbol,
            signal_action=signal.action.value,
            execution_mode=self._config.mode.value,
            order_id=order.order_id,
            trade_id=trade_id,
            order_status=order_status,
            quantity=quantity,
            order_price=signal.signal_price,
            reason_code=signal.reason_code,
            executed_at=datetime.now(timezone.utc),
        )

    def _calculate_quantity(
        self,
        signal: RealtimeSignal,
    ) -> Decimal:
        if signal.signal_price <= ZERO:
            raise ValueError(
                "signal_price must be greater than zero"
            )

        return (
            self._config.order_amount
            / signal.signal_price
        ).quantize(
            Decimal("0.00000001"),
            rounding=ROUND_DOWN,
        )

    def _skipped(
        self,
        *,
        signal: RealtimeSignal,
        reason_code: str,
    ) -> RealtimeExecutionResult:
        return RealtimeExecutionResult(
            exchange_code=signal.exchange_code,
            symbol=signal.symbol,
            signal_action=signal.action.value,
            execution_mode=self._config.mode.value,
            order_id=None,
            trade_id=None,
            order_status="SKIPPED",
            quantity=ZERO,
            order_price=signal.signal_price,
            reason_code=reason_code,
            executed_at=datetime.now(timezone.utc),
        )
