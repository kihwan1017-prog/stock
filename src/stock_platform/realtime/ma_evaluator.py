"""STEP 8-5-9 — Scope별 Moving Average Evaluator (전역 State 금지)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from stock_platform.realtime.hub_constants import (
    ConsumerWarmupStatus,
    SignalType,
)
from stock_platform.realtime.market_event import RealtimeMarketEvent
from stock_platform.realtime.strategy_models import (
    RealtimePositionState,
    RealtimeStrategyConfig,
)
from stock_platform.realtime.strategy_signal import StrategySignal
from stock_platform.strategy_deployment.runtime_scope import (
    StrategyRuntimeScope,
)


ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass
class ScopeStrategyState:
    """Scope 내부 종목별 전략 State — 다른 Scope와 공유 금지."""

    prices: deque[Decimal] = field(default_factory=deque)
    last_signal_type: str | None = None
    last_signal_at: datetime | None = None
    last_fingerprint: str | None = None
    last_sequence: int | None = None
    last_event_time: datetime | None = None
    warmup_status: ConsumerWarmupStatus = ConsumerWarmupStatus.WARMING_UP
    last_error: str | None = None
    previous_short: Decimal | None = None
    previous_long: Decimal | None = None


class MovingAverageStrategyEvaluator:
    """
    이동평균 Cross·손절·익절 계산만 담당.
    WebSocket / Scope Registry / 주문은 다루지 않는다.
    """

    def __init__(
        self,
        scope: StrategyRuntimeScope,
        config: RealtimeStrategyConfig | None = None,
    ) -> None:
        self.scope = scope
        self.config = config or RealtimeStrategyConfig()
        self._validate()
        self._by_symbol: dict[str, ScopeStrategyState] = {}

    def _validate(self) -> None:
        if self.config.short_window <= 0:
            raise ValueError("short_window must be > 0")
        if self.config.long_window <= self.config.short_window:
            raise ValueError(
                "long_window must be > short_window"
            )
        if self.config.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")

    def get_state(self, symbol: str) -> ScopeStrategyState:
        key = symbol.upper()
        if key not in self._by_symbol:
            state = ScopeStrategyState()
            state.prices = deque(maxlen=self.config.long_window + 1)
            self._by_symbol[key] = state
        return self._by_symbol[key]

    def warmup_status(self, symbol: str) -> ConsumerWarmupStatus:
        return self.get_state(symbol).warmup_status

    def evaluate(
        self,
        event: RealtimeMarketEvent,
        *,
        position: RealtimePositionState | None = None,
        allow_signal: bool = True,
    ) -> StrategySignal | None:
        """신호 없으면 None. HOLD/NO_ACTION은 발행하지 않음."""

        if event.price is None:
            return None
        symbol = event.symbol.upper()
        state = self.get_state(symbol)
        position = position or RealtimePositionState(
            quantity=ZERO, average_entry_price=None
        )

        # 중복·역순·오래된 Event
        if not self._accept_event(state, event):
            return None

        state.prices.append(event.price)
        short_avg = self._average(state.prices, self.config.short_window)
        long_avg = self._average(state.prices, self.config.long_window)

        # 보유 중 손절·익절은 warmup 여부와 무관하게 즉시 평가
        if (
            allow_signal
            and position.quantity > ZERO
            and position.average_entry_price is not None
        ):
            stop = position.average_entry_price * (
                ONE - self.config.stop_loss_ratio
            )
            take = position.average_entry_price * (
                ONE + self.config.take_profit_ratio
            )
            if event.price <= stop:
                return self._emit(
                    event, state, SignalType.SELL, "STOP_LOSS", short_avg, long_avg
                )
            if event.price >= take:
                return self._emit(
                    event, state, SignalType.SELL, "TAKE_PROFIT", short_avg, long_avg
                )

        if len(state.prices) < self.config.long_window + 1:
            state.warmup_status = ConsumerWarmupStatus.WARMING_UP
            state.previous_short = short_avg
            state.previous_long = long_avg
            return None

        state.warmup_status = ConsumerWarmupStatus.READY
        if not allow_signal:
            state.previous_short = short_avg
            state.previous_long = long_avg
            return None

        prev_s = state.previous_short
        prev_l = state.previous_long
        state.previous_short = short_avg
        state.previous_long = long_avg

        if (
            short_avg is None
            or long_avg is None
            or prev_s is None
            or prev_l is None
        ):
            return None

        # Golden / Dead Cross
        if (
            position.quantity <= ZERO
            and prev_s <= prev_l
            and short_avg > long_avg
            and self._passes_change(event)
        ):
            return self._emit(
                event, state, SignalType.BUY, "MA_GOLDEN_CROSS", short_avg, long_avg
            )
        if (
            position.quantity > ZERO
            and prev_s >= prev_l
            and short_avg < long_avg
        ):
            return self._emit(
                event, state, SignalType.SELL, "MA_DEAD_CROSS", short_avg, long_avg
            )
        return None

    def reset(self, symbol: str | None = None) -> None:
        if symbol is None:
            self._by_symbol.clear()
            return
        self._by_symbol.pop(symbol.upper(), None)

    def status(self) -> dict:
        return {
            "scope_key": self.scope.scope_key,
            "short_window": self.config.short_window,
            "long_window": self.config.long_window,
            "symbols": {
                sym: {
                    "warmup_status": st.warmup_status.value,
                    "buffer_len": len(st.prices),
                    "last_signal_type": st.last_signal_type,
                    "last_signal_at": (
                        st.last_signal_at.isoformat()
                        if st.last_signal_at
                        else None
                    ),
                    "last_error": st.last_error,
                }
                for sym, st in self._by_symbol.items()
            },
        }

    def _accept_event(
        self, state: ScopeStrategyState, event: RealtimeMarketEvent
    ) -> bool:
        from stock_platform.common.settings import get_settings

        max_age = float(
            getattr(get_settings(), "realtime_event_max_age_seconds", 10)
        )
        now = datetime.now(timezone.utc)
        age = (now - event.received_at).total_seconds()
        if age > max_age:
            return False
        if (
            state.last_sequence is not None
            and event.raw_sequence is not None
        ):
            if event.raw_sequence <= state.last_sequence:
                return False
        if (
            state.last_event_time is not None
            and event.event_time < state.last_event_time
            and event.raw_sequence is None
        ):
            return False
        if event.raw_sequence is not None:
            state.last_sequence = event.raw_sequence
        state.last_event_time = event.event_time
        return True

    def _passes_change(self, event: RealtimeMarketEvent) -> bool:
        if self.config.minimum_change_rate <= ZERO:
            return True
        if event.change_rate is None:
            return True
        return abs(event.change_rate) >= self.config.minimum_change_rate

    def _emit(
        self,
        event: RealtimeMarketEvent,
        state: ScopeStrategyState,
        signal_type: SignalType,
        reason: str,
        short_avg: Decimal | None,
        long_avg: Decimal | None,
    ) -> StrategySignal | None:
        now = datetime.now(timezone.utc)
        if (
            state.last_signal_at is not None
            and self.config.cooldown_seconds > 0
        ):
            elapsed = (now - state.last_signal_at).total_seconds()
            if elapsed < self.config.cooldown_seconds:
                return None

        fingerprint = StrategySignal.build_fingerprint(
            scope_key=self.scope.scope_key,
            symbol=event.symbol,
            signal_type=signal_type.value,
            reason_code=reason,
            event_time=event.event_time,
            sequence=event.raw_sequence,
        )
        if state.last_fingerprint == fingerprint:
            return None

        signal = StrategySignal(
            signal_id=StrategySignal.build_id(
                scope_key=self.scope.scope_key,
                symbol=event.symbol,
            ),
            fingerprint=fingerprint,
            scope_key=self.scope.scope_key,
            user_id=self.scope.user_id,
            account_kind=self.scope.account_kind.value,
            account_id=self.scope.account_id,
            strategy_id=self.scope.strategy_id,
            strategy_version=self.scope.strategy_version,
            broker_code=self.scope.broker_code,
            market_type=self.scope.market_type,
            symbol=event.symbol.upper(),
            signal_type=signal_type.value,
            generated_at=now,
            event_time=event.event_time,
            reference_price=event.price or ZERO,
            reason_code=reason,
            metadata={
                "short_average": (
                    str(short_avg) if short_avg is not None else None
                ),
                "long_average": (
                    str(long_avg) if long_avg is not None else None
                ),
                # 주문/원장 키는 시세 exchange (broker_code=데이터소스와 혼동 금지)
                "exchange_code": (
                    event.exchange_code or event.broker_code
                ),
            },
        )
        state.last_fingerprint = fingerprint
        state.last_signal_at = now
        state.last_signal_type = signal_type.value
        return signal

    @staticmethod
    def _average(
        prices: deque[Decimal], window: int
    ) -> Decimal | None:
        if len(prices) < window:
            return None
        values = list(prices)[-window:]
        return sum(values) / Decimal(window)
