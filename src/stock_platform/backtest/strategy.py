from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stock_platform.backtest.models import BacktestPrice


@dataclass(frozen=True, slots=True)
class MovingAverageStrategyConfig:
    short_window: int = 5
    long_window: int = 20
    stop_loss_ratio: Decimal = Decimal("0.05")
    take_profit_ratio: Decimal = Decimal("0.10")
    position_ratio: Decimal = Decimal("0.20")


class MovingAverageCrossStrategy:
    """단순 이동평균 골든크로스/데드크로스 전략."""

    def __init__(
        self,
        config: MovingAverageStrategyConfig | None = None,
    ) -> None:
        self.config = config or MovingAverageStrategyConfig()

    def should_enter(
        self,
        *,
        prices: list[BacktestPrice],
        index: int,
    ) -> tuple[bool, str]:
        if index < self.config.long_window:
            return False, "INSUFFICIENT_DATA"

        previous_short = self._average_close(
            prices,
            index - 1,
            self.config.short_window,
        )
        previous_long = self._average_close(
            prices,
            index - 1,
            self.config.long_window,
        )
        current_short = self._average_close(
            prices,
            index,
            self.config.short_window,
        )
        current_long = self._average_close(
            prices,
            index,
            self.config.long_window,
        )

        crossed = (
            previous_short <= previous_long
            and current_short > current_long
        )

        return (
            crossed,
            "MA_GOLDEN_CROSS" if crossed else "NO_ENTRY",
        )

    def should_exit(
        self,
        *,
        prices: list[BacktestPrice],
        index: int,
        entry_price: Decimal,
    ) -> tuple[bool, str]:
        current = prices[index]

        if current.low_price <= (
            entry_price
            * (Decimal("1") - self.config.stop_loss_ratio)
        ):
            return True, "STOP_LOSS"

        if current.high_price >= (
            entry_price
            * (Decimal("1") + self.config.take_profit_ratio)
        ):
            return True, "TAKE_PROFIT"

        if index < self.config.long_window:
            return False, "HOLD"

        current_short = self._average_close(
            prices,
            index,
            self.config.short_window,
        )
        current_long = self._average_close(
            prices,
            index,
            self.config.long_window,
        )

        if current_short < current_long:
            return True, "MA_DEAD_CROSS"

        return False, "HOLD"

    @staticmethod
    def _average_close(
        prices: list[BacktestPrice],
        index: int,
        window: int,
    ) -> Decimal:
        rows = prices[index - window + 1:index + 1]
        return (
            sum(
                (item.close_price for item in rows),
                Decimal("0"),
            )
            / Decimal(window)
        )
