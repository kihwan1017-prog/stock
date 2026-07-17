from datetime import date, timedelta
from decimal import Decimal

from stock_platform.indicators.engine import IndicatorEngine
from stock_platform.indicators.models import PriceBar


def _bars(count: int = 80) -> list[PriceBar]:
    start = date(2026, 1, 1)

    return [
        PriceBar(
            trade_date=start + timedelta(days=index),
            open_price=Decimal(100 + index),
            high_price=Decimal(102 + index),
            low_price=Decimal(98 + index),
            close_price=Decimal(101 + index),
            volume=Decimal(1000 + index * 10),
        )
        for index in range(count)
    ]


def test_calculates_major_indicators() -> None:
    engine = IndicatorEngine()
    result = engine.calculate(_bars())

    latest = result[-1]

    assert latest.ma5 is not None
    assert latest.ma20 is not None
    assert latest.ma60 is not None
    assert latest.ema12 is not None
    assert latest.ema26 is not None
    assert latest.rsi14 is not None
    assert latest.macd is not None
    assert latest.macd_signal is not None
    assert latest.macd_histogram is not None
    assert latest.bollinger_middle is not None
    assert latest.bollinger_upper is not None
    assert latest.bollinger_lower is not None
    assert latest.atr14 is not None
    assert latest.volume_ma20 is not None
    assert latest.status_code in {
        "READY",
        "PARTIAL",
        "INSUFFICIENT",
    }


def test_empty_input_returns_empty_result() -> None:
    engine = IndicatorEngine()

    assert engine.calculate([]) == []


def test_rsi_for_steady_rising_prices_is_high() -> None:
    engine = IndicatorEngine()
    result = engine.calculate(_bars(40))

    assert result[-1].rsi14 == Decimal("100")
