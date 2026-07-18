from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionResult,
)
from stock_platform.realtime.order_executor import (
    RealtimePaperOrderExecutor,
)
from stock_platform.realtime.safety_guard import (
    RealtimeOrderSafetyGuard,
)
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
)
from stock_platform.risk_engine.kill_switch_guard import (
    PersistentKillSwitchGuard,
)
from stock_platform.risk_engine.order_guard import (
    DatabaseBackedRiskOrderGuard,
)


class RiskIntegratedRealtimeOrderExecutor:
    """
    기본 설정 검증 → Persistent Kill Switch
    → Risk Engine → Safety Guard → OrderExecutionService.
    """

    def __init__(
        self,
        *,
        session: Session,
        execution_config: RealtimeExecutionConfig,
        safety_guard: RealtimeOrderSafetyGuard,
    ) -> None:
        self._session = session
        self._execution_config = execution_config
        self._safety_guard = safety_guard

    def execute(
        self,
        signal: RealtimeSignal,
    ) -> RealtimeExecutionResult:
        account_number = (
            get_settings().kiwoom_account_number.strip()
        )

        if not account_number:
            return self._skipped(
                signal,
                "RISK_ACCOUNT_NUMBER_MISSING",
            )

        try:
            PersistentKillSwitchGuard(
                self._session
            ).require_order_allowed(
                side=signal.action.value,
                allow_sell=True,
            )
        except PermissionError:
            return self._skipped(
                signal,
                "GLOBAL_KILL_SWITCH_ACTIVE",
            )

        quantity = (
            self._execution_config.order_amount
            / signal.signal_price
        ).quantize(Decimal("0.00000001"))

        risk_result = DatabaseBackedRiskOrderGuard(
            self._session
        ).check(
            account_number=account_number,
            account_id=self._execution_config.account_id,
            exchange_code=signal.exchange_code,
            symbol=signal.symbol,
            side=signal.action.value,
            quantity=quantity,
            price=signal.signal_price,
        )

        if not risk_result.allowed:
            return self._skipped(
                signal,
                risk_result.blocked_reason
                or "RISK_ENGINE_BLOCKED",
            )

        from stock_platform.trading.account_models import (
            PaperPosition,
        )
        from sqlalchemy import func, select

        open_position_count = self._session.scalar(
            select(func.count())
            .select_from(PaperPosition)
            .where(
                PaperPosition.account_id
                == self._execution_config.account_id,
                PaperPosition.quantity > 0,
            )
        ) or 0

        decision = self._safety_guard.evaluate(
            signal=signal,
            mode=self._execution_config.mode,
            order_amount=self._execution_config.order_amount,
            open_position_count=int(open_position_count),
        )
        if not decision.allowed:
            return self._skipped(
                signal,
                decision.reason_code,
            )

        result = OrderExecutionService(self._session).submit(
            OrderExecutionCommand(
                account_id=self._execution_config.account_id,
                broker_code="KIWOOM",
                exchange_code=signal.exchange_code,
                symbol=signal.symbol,
                side=OrderSide(signal.action.value),
                order_type=OrderType.LIMIT,
                quantity=None,
                order_amount=self._execution_config.order_amount,
                price=signal.signal_price,
                strategy_code=signal.reason_code,
                account_number=account_number,
                skip_risk_checks=True,  # 이미 상단에서 검증
                metadata_payload={
                    "source": "REALTIME_SIGNAL",
                    "signal_reason": signal.reason_code,
                    "execution_mode": (
                        self._execution_config.mode.value
                    ),
                },
                actor="REALTIME_EXECUTION",
                idempotency_key=(
                    f"RT:{signal.exchange_code}:"
                    f"{signal.symbol}:"
                    f"{signal.action.value}:"
                    f"{signal.generated_at.isoformat()}"
                ),
            )
        )

        if not result.allowed:
            return self._skipped(
                signal,
                result.reason_code,
            )

        self._safety_guard.mark_order_executed(signal)

        return RealtimeExecutionResult(
            exchange_code=signal.exchange_code,
            symbol=signal.symbol,
            signal_action=signal.action.value,
            execution_mode=self._execution_config.mode.value,
            order_id=result.order_id,
            trade_id=None,
            order_status=result.status_code or "PENDING",
            quantity=result.quantity or Decimal("0"),
            order_price=result.price or signal.signal_price,
            reason_code=result.reason_code,
            executed_at=datetime.now(timezone.utc),
        )

    def _skipped(
        self,
        signal: RealtimeSignal,
        reason_code: str,
    ) -> RealtimeExecutionResult:
        executor = RealtimePaperOrderExecutor.__new__(
            RealtimePaperOrderExecutor
        )
        executor._config = self._execution_config

        return executor._skipped(
            signal=signal,
            reason_code=reason_code,
        )
