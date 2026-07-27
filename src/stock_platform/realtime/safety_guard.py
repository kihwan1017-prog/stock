from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from decimal import Decimal

from stock_platform.realtime.execution_models import (
    RealtimeExecutionMode,
)
from stock_platform.realtime.safety_models import (
    RealtimeOrderSafetyConfig,
    SafetyDecision,
)
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)


ZERO = Decimal("0")


class RealtimeOrderSafetyGuard:
    """실시간 주문 전 공통 안전장치를 평가한다."""

    def __init__(
        self,
        config: RealtimeOrderSafetyConfig,
    ) -> None:
        self._config = config
        self._last_order_at: dict[str, datetime] = {}
        self._last_signal_key_at: dict[str, datetime] = {}
        self._order_times: deque[datetime] = deque()
        self._daily_realized_loss = ZERO

    def evaluate(
        self,
        *,
        signal: RealtimeSignal,
        mode: RealtimeExecutionMode,
        order_amount: Decimal,
        open_position_count: int,
        live_unlock_token: str | None = None,
    ) -> SafetyDecision:
        now = datetime.now(timezone.utc)
        self._cleanup_rate_window(now)

        if signal.action == RealtimeSignalAction.HOLD:
            return SafetyDecision(
                allowed=False,
                reason_code="HOLD_SIGNAL",
                message="HOLD signal does not create an order",
            )

        if order_amount <= ZERO:
            return SafetyDecision(
                allowed=False,
                reason_code="INVALID_ORDER_AMOUNT",
                message="order_amount must be greater than zero",
            )

        if order_amount > self._config.max_order_amount:
            return SafetyDecision(
                allowed=False,
                reason_code="MAX_ORDER_AMOUNT_EXCEEDED",
                message=(
                    f"order amount exceeds "
                    f"{self._config.max_order_amount}"
                ),
            )

        if (
            self._daily_realized_loss
            >= self._config.max_daily_loss
        ):
            return SafetyDecision(
                allowed=False,
                reason_code="DAILY_LOSS_LIMIT_REACHED",
                message="daily loss limit reached",
            )

        if (
            signal.action == RealtimeSignalAction.BUY
            and open_position_count
            >= self._config.max_open_positions
        ):
            return SafetyDecision(
                allowed=False,
                reason_code="MAX_OPEN_POSITIONS_REACHED",
                message="maximum open position count reached",
            )

        if (
            signal.exchange_code.upper() == "KRX"
            and self._config.enforce_market_hours_for_krx
        ):
            # STEP 8-5-13 — 고정 trading_start/end_time 대신
            # Session Timeline Phase 사용 (지연개장/조기종료 반영).
            # trading_start_time/trading_end_time은 config 하위호환용으로
            # 유지되나 KRX LIVE 판단에는 더 이상 사용하지 않는다.
            from stock_platform.operation.session_timeline import (
                SessionTimelineReasonCode,
                phase_reason_code,
                resolve_krx_timeline,
            )

            try:
                timeline = resolve_krx_timeline(moment=now)
            except Exception:  # noqa: BLE001
                return SafetyDecision(
                    allowed=False,
                    reason_code=(
                        SessionTimelineReasonCode.CALENDAR_UNAVAILABLE.value
                    ),
                    message="KRX session timeline unavailable",
                )

            # BUY는 신규진입(OPEN)만 허용, SELL/EXIT은 위험축소로 간주해
            # OPEN·EXIT_ONLY Phase 모두 허용한다.
            is_risk_reducing = (
                signal.action == RealtimeSignalAction.SELL
            )
            if not timeline.allows_any_order(
                now, is_risk_reducing=is_risk_reducing
            ):
                phase = timeline.phase_at(now)
                return SafetyDecision(
                    allowed=False,
                    reason_code=phase_reason_code(phase),
                    message=(
                        f"KRX order blocked by session phase "
                        f"{phase.value}"
                    ),
                )

        symbol_key = self._symbol_key(signal)
        signal_key = self._signal_key(signal)

        previous_order = self._last_order_at.get(symbol_key)
        if previous_order is not None:
            seconds = (now - previous_order).total_seconds()
            if seconds < self._config.symbol_cooldown_seconds:
                return SafetyDecision(
                    allowed=False,
                    reason_code="SYMBOL_COOLDOWN",
                    message="symbol cooldown is active",
                )

        previous_same_signal = self._last_signal_key_at.get(
            signal_key
        )
        if previous_same_signal is not None:
            seconds = (
                now - previous_same_signal
            ).total_seconds()
            if (
                seconds
                < self._config.duplicate_order_window_seconds
            ):
                return SafetyDecision(
                    allowed=False,
                    reason_code="DUPLICATE_ORDER_BLOCKED",
                    message="duplicate signal order blocked",
                )

        if (
            len(self._order_times)
            >= self._config.max_orders_per_minute
        ):
            return SafetyDecision(
                allowed=False,
                reason_code="ORDER_RATE_LIMIT",
                message="maximum orders per minute reached",
            )

        if mode == RealtimeExecutionMode.LIVE:
            if not self._config.live_trading_enabled:
                return SafetyDecision(
                    allowed=False,
                    reason_code="LIVE_TRADING_DISABLED",
                    message="live trading switch is disabled",
                )

            expected = self._config.live_unlock_token.strip()
            supplied = (live_unlock_token or "").strip()

            if not expected or supplied != expected:
                return SafetyDecision(
                    allowed=False,
                    reason_code="LIVE_UNLOCK_FAILED",
                    message="live trading unlock token is invalid",
                )

        return SafetyDecision(
            allowed=True,
            reason_code="ALLOWED",
            message="order passed safety checks",
        )

    def mark_order_executed(
        self,
        signal: RealtimeSignal,
    ) -> None:
        now = datetime.now(timezone.utc)
        self._last_order_at[self._symbol_key(signal)] = now
        self._last_signal_key_at[
            self._signal_key(signal)
        ] = now
        self._order_times.append(now)

    def add_realized_profit_loss(
        self,
        realized_profit_loss: Decimal,
    ) -> None:
        if realized_profit_loss < ZERO:
            self._daily_realized_loss += (
                -realized_profit_loss
            )

    def reset_daily_counters(self) -> None:
        self._daily_realized_loss = ZERO
        self._order_times.clear()

    @property
    def daily_realized_loss(self) -> Decimal:
        return self._daily_realized_loss

    @staticmethod
    def _symbol_key(
        signal: RealtimeSignal,
    ) -> str:
        return (
            f"{signal.exchange_code.upper()}:"
            f"{signal.symbol.upper()}"
        )

    @classmethod
    def _signal_key(
        cls,
        signal: RealtimeSignal,
    ) -> str:
        return (
            f"{cls._symbol_key(signal)}:"
            f"{signal.action.value}:"
            f"{signal.reason_code}"
        )

    def _cleanup_rate_window(
        self,
        now: datetime,
    ) -> None:
        while self._order_times:
            age = (
                now - self._order_times[0]
            ).total_seconds()
            if age <= 60:
                break
            self._order_times.popleft()
