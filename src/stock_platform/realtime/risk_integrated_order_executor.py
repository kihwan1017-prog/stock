from __future__ import annotations

import os
from decimal import Decimal

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
from stock_platform.risk_engine.kill_switch_guard import (
    PersistentKillSwitchGuard,
)
from stock_platform.risk_engine.order_guard import (
    DatabaseBackedRiskOrderGuard,
)


class RiskIntegratedRealtimeOrderExecutor:
    """
    기본 설정 검증 → Persistent Kill Switch
    → Risk Engine → Safety Guard → 주문 실행.
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
        account_number = os.getenv(
            "KIWOOM_ACCOUNT_NUMBER",
            "",
        ).strip()

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
                "RISK_ENGINE_BLOCKED",
            )

        from stock_platform.realtime.safe_order_executor import (
            SafeRealtimeOrderExecutor,
        )

        return SafeRealtimeOrderExecutor(
            session=self._session,
            execution_config=self._execution_config,
            safety_guard=self._safety_guard,
        ).execute(signal)

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