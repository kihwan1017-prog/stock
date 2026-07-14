from datetime import datetime, timezone
from decimal import Decimal

from stock_platform.realtime.models import (
    MarketEventType,
    RealtimeQuote,
)
from stock_platform.realtime.strategy import (
    RealtimeMovingAverageStrategy,
)
from stock_platform.realtime.strategy_models import (
    RealtimePositionState,
    RealtimeSignalAction,
    RealtimeStrategyConfig,
)


def _quote(
    price: str,
    change_rate: str = "0.01",
) -> RealtimeQuote:
    now = datetime.now(timezone.utc)
    return RealtimeQuote(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        event_type=MarketEventType.TICKER,
        trade_price=Decimal(price),
        opening_price=None,
        high_price=None,
        low_price=None,
        previous_close_price=None,
        change_price=None,
        change_rate=Decimal(change_rate),
        accumulated_volume=None,
        trade_volume=None,
        event_time=now,
        received_at=now,
        source_code="TEST",
    )


def test_generates_golden_cross_buy_signal() -> None:
    strategy = RealtimeMovingAverageStrategy(
        RealtimeStrategyConfig(
            short_window=2,
            long_window=3,
            cooldown_seconds=0,
        )
    )
    position = RealtimePositionState(
        quantity=Decimal("0"),
        average_entry_price=None,
    )

    signals = [
        strategy.evaluate(
            quote=_quote(price),
            position=position,
        )
        for price in [
            "10",
            "9",
            "8",
            "11",
        ]
    ]

    assert signals[-1].action == (
        RealtimeSignalAction.BUY
    )
    assert signals[-1].reason_code == (
        "MA_GOLDEN_CROSS"
    )


def test_generates_stop_loss_signal() -> None:
    strategy = RealtimeMovingAverageStrategy(
        RealtimeStrategyConfig(
            short_window=2,
            long_window=3,
            stop_loss_ratio=Decimal("0.05"),
        )
    )
    position = RealtimePositionState(
        quantity=Decimal("1"),
        average_entry_price=Decimal("100"),
    )

    signal = strategy.evaluate(
        quote=_quote("94"),
        position=position,
    )

    assert signal.action == (
        RealtimeSignalAction.SELL
    )
    assert signal.reason_code == "STOP_LOSS"


def test_generates_take_profit_signal() -> None:
    strategy = RealtimeMovingAverageStrategy(
        RealtimeStrategyConfig(
            short_window=2,
            long_window=3,
            take_profit_ratio=Decimal("0.10"),
        )
    )
    position = RealtimePositionState(
        quantity=Decimal("1"),
        average_entry_price=Decimal("100"),
    )

    signal = strategy.evaluate(
        quote=_quote("111"),
        position=position,
    )

    assert signal.action == (
        RealtimeSignalAction.SELL
    )
    assert signal.reason_code == "TAKE_PROFIT"
