from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from decimal import Decimal

from stock_platform.realtime.models import RealtimeQuote
from stock_platform.realtime.strategy_models import (
    RealtimePositionState,
    RealtimeSignal,
    RealtimeSignalAction,
    RealtimeStrategyConfig,
)


ZERO = Decimal("0")
ONE = Decimal("1")


class RealtimeMovingAverageStrategy:
    """
    실시간 가격 이력으로 이동평균 교차와 손절·익절 신호를 생성한다.
    """

    def __init__(
        self,
        config: RealtimeStrategyConfig | None = None,
    ) -> None:
        self.config = config or RealtimeStrategyConfig()
        self._validate_config()
        self._prices: dict[
            str,
            deque[Decimal],
        ] = defaultdict(
            lambda: deque(
                maxlen=self.config.long_window + 1
            )
        )

    def evaluate(
        self,
        *,
        quote: RealtimeQuote,
        position: RealtimePositionState,
    ) -> RealtimeSignal:
        key = self._key(
            quote.exchange_code,
            quote.symbol,
        )
        history = self._prices[key]
        history.append(quote.trade_price)

        short_average = self._average(
            history,
            self.config.short_window,
        )
        long_average = self._average(
            history,
            self.config.long_window,
        )

        if (
            position.quantity > ZERO
            and position.average_entry_price is not None
        ):
            stop_price = (
                position.average_entry_price
                * (ONE - self.config.stop_loss_ratio)
            )
            take_price = (
                position.average_entry_price
                * (ONE + self.config.take_profit_ratio)
            )

            if quote.trade_price <= stop_price:
                return self._signal(
                    quote=quote,
                    action=RealtimeSignalAction.SELL,
                    short_average=short_average,
                    long_average=long_average,
                    reason_code="STOP_LOSS",
                )

            if quote.trade_price >= take_price:
                return self._signal(
                    quote=quote,
                    action=RealtimeSignalAction.SELL,
                    short_average=short_average,
                    long_average=long_average,
                    reason_code="TAKE_PROFIT",
                )

        if len(history) < self.config.long_window + 1:
            return self._signal(
                quote=quote,
                action=RealtimeSignalAction.HOLD,
                short_average=short_average,
                long_average=long_average,
                reason_code="INSUFFICIENT_DATA",
            )

        prices = list(history)

        previous_short = self._average_from_list(
            prices[:-1],
            self.config.short_window,
        )
        previous_long = self._average_from_list(
            prices[:-1],
            self.config.long_window,
        )
        current_short = self._average_from_list(
            prices,
            self.config.short_window,
        )
        current_long = self._average_from_list(
            prices,
            self.config.long_window,
        )

        if (
            position.quantity <= ZERO
            and previous_short is not None
            and previous_long is not None
            and current_short is not None
            and current_long is not None
            and previous_short <= previous_long
            and current_short > current_long
            and self._passes_change_rate(quote)
        ):
            return self._signal(
                quote=quote,
                action=RealtimeSignalAction.BUY,
                short_average=current_short,
                long_average=current_long,
                reason_code="MA_GOLDEN_CROSS",
            )

        if (
            position.quantity > ZERO
            and previous_short is not None
            and previous_long is not None
            and current_short is not None
            and current_long is not None
            and previous_short >= previous_long
            and current_short < current_long
        ):
            return self._signal(
                quote=quote,
                action=RealtimeSignalAction.SELL,
                short_average=current_short,
                long_average=current_long,
                reason_code="MA_DEAD_CROSS",
            )

        return self._signal(
            quote=quote,
            action=RealtimeSignalAction.HOLD,
            short_average=current_short,
            long_average=current_long,
            reason_code="NO_SIGNAL",
        )

    def reset(
        self,
        *,
        exchange_code: str | None = None,
        symbol: str | None = None,
    ) -> None:
        if exchange_code and symbol:
            self._prices.pop(
                self._key(exchange_code, symbol),
                None,
            )
            return

        self._prices.clear()

    def _passes_change_rate(
        self,
        quote: RealtimeQuote,
    ) -> bool:
        if self.config.minimum_change_rate <= ZERO:
            return True

        if quote.change_rate is None:
            return False

        return quote.change_rate >= (
            self.config.minimum_change_rate
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

    @staticmethod
    def _average(
        values: deque[Decimal],
        window: int,
    ) -> Decimal | None:
        return RealtimeMovingAverageStrategy._average_from_list(
            list(values),
            window,
        )

    @staticmethod
    def _average_from_list(
        values: list[Decimal],
        window: int,
    ) -> Decimal | None:
        if len(values) < window:
            return None

        rows = values[-window:]
        return (
            sum(rows, ZERO)
            / Decimal(window)
        ).quantize(Decimal("0.00000001"))

    @staticmethod
    def _signal(
        *,
        quote: RealtimeQuote,
        action: RealtimeSignalAction,
        short_average: Decimal | None,
        long_average: Decimal | None,
        reason_code: str,
    ) -> RealtimeSignal:
        return RealtimeSignal(
            exchange_code=quote.exchange_code,
            symbol=quote.symbol,
            action=action,
            signal_price=quote.trade_price,
            short_average=short_average,
            long_average=long_average,
            change_rate=quote.change_rate,
            reason_code=reason_code,
            generated_at=datetime.now(timezone.utc),
        )

    def _validate_config(self) -> None:
        if self.config.short_window < 2:
            raise ValueError(
                "short_window must be at least 2"
            )

        if (
            self.config.long_window
            <= self.config.short_window
        ):
            raise ValueError(
                "long_window must be greater than short_window"
            )

        for name, value in {
            "minimum_change_rate": (
                self.config.minimum_change_rate
            ),
            "stop_loss_ratio": (
                self.config.stop_loss_ratio
            ),
            "take_profit_ratio": (
                self.config.take_profit_ratio
            ),
        }.items():
            if value < ZERO or value > ONE:
                raise ValueError(
                    f"{name} must be between 0 and 1"
                )

        if self.config.cooldown_seconds < 0:
            raise ValueError(
                "cooldown_seconds must not be negative"
            )
