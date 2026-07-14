from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import structlog

from stock_platform.realtime.bus import RealtimeQuoteBus
from stock_platform.realtime.signal_bus import (
    RealtimeSignalBus,
)
from stock_platform.realtime.strategy import (
    RealtimeMovingAverageStrategy,
)
from stock_platform.realtime.strategy_models import (
    RealtimePositionState,
    RealtimeSignal,
    RealtimeSignalAction,
    RealtimeStrategyConfig,
)


logger = structlog.get_logger(__name__)
ZERO = Decimal("0")


class RealtimeStrategyRunner:
    """실시간 시세 버스를 구독하여 전략을 실행한다."""

    def __init__(
        self,
        *,
        quote_bus: RealtimeQuoteBus,
        signal_bus: RealtimeSignalBus,
        config: RealtimeStrategyConfig | None = None,
    ) -> None:
        self._quote_bus = quote_bus
        self._signal_bus = signal_bus
        self._strategy = RealtimeMovingAverageStrategy(
            config
        )
        self._positions: dict[
            str,
            RealtimePositionState,
        ] = {}
        self._last_signal_at: dict[
            str,
            datetime,
        ] = {}
        self._task: asyncio.Task | None = None
        self._running = False
        self._processed_count = 0
        self._published_count = 0
        self._last_error: str | None = None

    async def start(self) -> dict:
        if self._task is not None:
            raise ValueError(
                "Realtime strategy runner is already running"
            )

        self._task = asyncio.create_task(
            self.run_forever(),
            name="realtime-strategy-runner",
        )
        return self.status()

    async def run_forever(self) -> None:
        self._running = True

        try:
            async for quote in self._quote_bus.subscribe():
                try:
                    self._processed_count += 1
                    key = self._key(
                        quote.exchange_code,
                        quote.symbol,
                    )
                    position = self._positions.get(
                        key,
                        RealtimePositionState(
                            quantity=ZERO,
                            average_entry_price=None,
                        ),
                    )

                    signal = self._strategy.evaluate(
                        quote=quote,
                        position=position,
                    )

                    if signal.action == (
                        RealtimeSignalAction.HOLD
                    ):
                        continue

                    if self._is_in_cooldown(signal):
                        continue

                    self._last_signal_at[key] = (
                        signal.generated_at
                    )
                    self._published_count += 1
                    await self._signal_bus.publish(signal)

                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._last_error = str(exc)
                    logger.exception(
                        "realtime_strategy_evaluation_failed",
                    )
        finally:
            self._running = False

    async def stop(self) -> None:
        if self._task is None:
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    def set_position(
        self,
        *,
        exchange_code: str,
        symbol: str,
        quantity: Decimal,
        average_entry_price: Decimal | None,
    ) -> RealtimePositionState:
        if quantity < ZERO:
            raise ValueError(
                "quantity must not be negative"
            )

        if (
            quantity > ZERO
            and (
                average_entry_price is None
                or average_entry_price <= ZERO
            )
        ):
            raise ValueError(
                "average_entry_price is required "
                "for an open position"
            )

        state = RealtimePositionState(
            quantity=quantity,
            average_entry_price=average_entry_price,
        )
        self._positions[
            self._key(exchange_code, symbol)
        ] = state
        return state

    def get_position(
        self,
        *,
        exchange_code: str,
        symbol: str,
    ) -> RealtimePositionState:
        return self._positions.get(
            self._key(exchange_code, symbol),
            RealtimePositionState(
                quantity=ZERO,
                average_entry_price=None,
            ),
        )

    def status(self) -> dict:
        return {
            "running": self._running,
            "processed_count": self._processed_count,
            "published_count": self._published_count,
            "position_count": len(self._positions),
            "last_error": self._last_error,
            "signal_subscriber_count": (
                self._signal_bus.subscriber_count
            ),
            "config": {
                "short_window": (
                    self._strategy.config.short_window
                ),
                "long_window": (
                    self._strategy.config.long_window
                ),
                "minimum_change_rate": str(
                    self._strategy.config
                    .minimum_change_rate
                ),
                "stop_loss_ratio": str(
                    self._strategy.config
                    .stop_loss_ratio
                ),
                "take_profit_ratio": str(
                    self._strategy.config
                    .take_profit_ratio
                ),
                "cooldown_seconds": (
                    self._strategy.config
                    .cooldown_seconds
                ),
            },
        }

    def _is_in_cooldown(
        self,
        signal: RealtimeSignal,
    ) -> bool:
        key = self._key(
            signal.exchange_code,
            signal.symbol,
        )
        previous = self._last_signal_at.get(key)

        if previous is None:
            return False

        seconds = (
            datetime.now(timezone.utc) - previous
        ).total_seconds()

        return seconds < (
            self._strategy.config.cooldown_seconds
        )

    @staticmethod
    def _key(
        exchange_code: str,
        symbol: str,
    ) -> str:
        return (
            f"{exchange_code.upper()}:"
            f"{symbol.upper()}"
        )
