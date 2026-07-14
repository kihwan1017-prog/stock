from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
    PaperPosition,
)


class SafeRealtimeOrderExecutor:
    """안전검사 통과 후 기존 모의 주문 실행기를 호출한다."""

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

        result = RealtimePaperOrderExecutor(
            session=self._session,
            config=self._execution_config,
        ).execute(signal)

        if result.order_status != "SKIPPED":
            self._safety_guard.mark_order_executed(
                signal
            )

        return result
