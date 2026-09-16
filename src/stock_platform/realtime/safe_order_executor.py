from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.order.trading_guards import (
    TradingGuardError,
    require_order_safety,
)
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
from stock_platform.trading.account_models import (
    PaperAccount,
    PaperPosition,
)


class SafeRealtimeOrderExecutor:
    """안전검사 + Risk Engine 통과 후 모의 주문 실행."""

    def __init__(
        self,
        *,
        session: Session,
        execution_config: RealtimeExecutionConfig,
        safety_guard: RealtimeOrderSafetyGuard,
        live_unlock_token: str | None = None,
    ) -> None:
        self._session = session
        self._execution_config = execution_config
        self._safety_guard = safety_guard
        self._live_unlock_token = live_unlock_token

    def execute(
        self,
        signal: RealtimeSignal,
    ) -> RealtimeExecutionResult:
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
            order_amount=(
                self._execution_config.order_amount
            ),
            open_position_count=int(
                open_position_count
            ),
            live_unlock_token=self._live_unlock_token,
        )

        if not decision.allowed:
            executor = RealtimePaperOrderExecutor.__new__(
                RealtimePaperOrderExecutor
            )
            executor._config = self._execution_config
            return executor._skipped(
                signal=signal,
                reason_code=decision.reason_code,
            )

        # STEP8-2: Safe 경로도 Risk Engine 강제
        user_id = self._execution_config.user_id
        if user_id is None:
            paper = self._session.get(
                PaperAccount, self._execution_config.account_id
            )
            if paper is not None and paper.user_id is not None:
                user_id = int(paper.user_id)
        quantity = (
            self._execution_config.order_amount
            / signal.signal_price
        ).quantize(Decimal("0.00000001"))
        account_number = (
            get_settings().kiwoom_account_number.strip()
            or f"PAPER-{self._execution_config.account_id}"
        )
        try:
            require_order_safety(
                self._session,
                side=signal.action.value,
                account_number=account_number,
                account_id=self._execution_config.account_id,
                exchange_code=signal.exchange_code,
                symbol=signal.symbol,
                quantity=quantity,
                price=signal.signal_price,
                broker_code="PAPER",
                user_id=user_id,
                user_broker_account_id=(
                    self._execution_config.user_broker_account_id
                ),
                order_source="AUTO",
                is_risk_reducing=(
                    signal.action.value.upper() == "SELL"
                ),
            )
        except TradingGuardError as exc:
            executor = RealtimePaperOrderExecutor.__new__(
                RealtimePaperOrderExecutor
            )
            executor._config = self._execution_config
            return executor._skipped(
                signal=signal,
                reason_code=str(exc)[:80] or "RISK_ENGINE_BLOCKED",
            )

        result = RealtimePaperOrderExecutor(
            session=self._session,
            config=self._execution_config,
        ).execute(signal)

        if result.order_status != "SKIPPED":
            self._safety_guard.mark_order_executed(
                signal
            )

        return result
