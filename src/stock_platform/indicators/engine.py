from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, getcontext

from stock_platform.indicators.models import (
    REQUIRED_INDICATOR_FIELDS,
    DailyIndicator,
    PriceBar,
)

getcontext().prec = 28

ZERO = Decimal("0")
TWO = Decimal("2")


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, ZERO) / Decimal(len(values))


def _stddev_population(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("values must not be empty")

    mean = _mean(values)
    variance = sum(
        ((value - mean) ** 2 for value in values),
        ZERO,
    ) / Decimal(len(values))

    return variance.sqrt()


def _rolling_mean(
    values: Sequence[Decimal],
    period: int,
) -> list[Decimal | None]:
    if period <= 0:
        raise ValueError("period must be greater than zero")

    result: list[Decimal | None] = [None] * len(values)
    rolling_sum = ZERO

    for index, value in enumerate(values):
        rolling_sum += value

        if index >= period:
            rolling_sum -= values[index - period]

        if index >= period - 1:
            result[index] = rolling_sum / Decimal(period)

    return result


def _ema(
    values: Sequence[Decimal],
    period: int,
) -> list[Decimal | None]:
    if period <= 0:
        raise ValueError("period must be greater than zero")

    result: list[Decimal | None] = [None] * len(values)

    if len(values) < period:
        return result

    seed = _mean(values[:period])
    result[period - 1] = seed

    multiplier = TWO / Decimal(period + 1)
    previous = seed

    for index in range(period, len(values)):
        current = (
            (values[index] - previous) * multiplier
            + previous
        )
        result[index] = current
        previous = current

    return result


def _rsi_wilder(
    values: Sequence[Decimal],
    period: int = 14,
) -> list[Decimal | None]:
    result: list[Decimal | None] = [None] * len(values)

    if len(values) <= period:
        return result

    gains: list[Decimal] = []
    losses: list[Decimal] = []

    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        gains.append(max(change, ZERO))
        losses.append(max(-change, ZERO))

    average_gain = _mean(gains)
    average_loss = _mean(losses)

    result[period] = _rsi_from_averages(
        average_gain,
        average_loss,
    )

    period_decimal = Decimal(period)

    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = max(change, ZERO)
        loss = max(-change, ZERO)

        average_gain = (
            (average_gain * Decimal(period - 1)) + gain
        ) / period_decimal
        average_loss = (
            (average_loss * Decimal(period - 1)) + loss
        ) / period_decimal

        result[index] = _rsi_from_averages(
            average_gain,
            average_loss,
        )

    return result


def _rsi_from_averages(
    average_gain: Decimal,
    average_loss: Decimal,
) -> Decimal:
    if average_loss == ZERO:
        if average_gain == ZERO:
            return Decimal("50")
        return Decimal("100")

    relative_strength = average_gain / average_loss
    return Decimal("100") - (
        Decimal("100")
        / (Decimal("1") + relative_strength)
    )


def _macd(
    values: Sequence[Decimal],
) -> tuple[
    list[Decimal | None],
    list[Decimal | None],
    list[Decimal | None],
]:
    ema12 = _ema(values, 12)
    ema26 = _ema(values, 26)

    macd_values: list[Decimal | None] = [None] * len(values)

    for index in range(len(values)):
        if ema12[index] is not None and ema26[index] is not None:
            macd_values[index] = ema12[index] - ema26[index]

    available_macd = [
        value
        for value in macd_values
        if value is not None
    ]
    signal_available = _ema(available_macd, 9)

    signal: list[Decimal | None] = [None] * len(values)
    histogram: list[Decimal | None] = [None] * len(values)

    available_index = 0
    for index, macd_value in enumerate(macd_values):
        if macd_value is None:
            continue

        signal_value = signal_available[available_index]
        signal[index] = signal_value

        if signal_value is not None:
            histogram[index] = macd_value - signal_value

        available_index += 1

    return macd_values, signal, histogram


def _bollinger(
    values: Sequence[Decimal],
    period: int = 20,
    multiplier: Decimal = Decimal("2"),
) -> tuple[
    list[Decimal | None],
    list[Decimal | None],
    list[Decimal | None],
]:
    middle = _rolling_mean(values, period)
    upper: list[Decimal | None] = [None] * len(values)
    lower: list[Decimal | None] = [None] * len(values)

    for index in range(period - 1, len(values)):
        window = values[index - period + 1:index + 1]
        standard_deviation = _stddev_population(window)

        upper[index] = (
            middle[index]
            + multiplier * standard_deviation
        )
        lower[index] = (
            middle[index]
            - multiplier * standard_deviation
        )

    return middle, upper, lower


def _atr_wilder(
    bars: Sequence[PriceBar],
    period: int = 14,
) -> list[Decimal | None]:
    result: list[Decimal | None] = [None] * len(bars)

    if len(bars) < period:
        return result

    true_ranges: list[Decimal] = []

    for index, bar in enumerate(bars):
        if index == 0:
            true_range = bar.high_price - bar.low_price
        else:
            previous_close = bars[index - 1].close_price
            true_range = max(
                bar.high_price - bar.low_price,
                abs(bar.high_price - previous_close),
                abs(bar.low_price - previous_close),
            )

        true_ranges.append(true_range)

    initial_atr = _mean(true_ranges[:period])
    result[period - 1] = initial_atr
    previous_atr = initial_atr

    for index in range(period, len(true_ranges)):
        current_atr = (
            previous_atr * Decimal(period - 1)
            + true_ranges[index]
        ) / Decimal(period)

        result[index] = current_atr
        previous_atr = current_atr

    return result


def _rolling_52w(
    bars: Sequence[PriceBar],
    lookback: int = 252,
) -> tuple[list[Decimal | None], list[Decimal | None]]:
    """약 252거래일 기준 52주 고저. 부족하면 None."""

    highs: list[Decimal | None] = [None] * len(bars)
    lows: list[Decimal | None] = [None] * len(bars)

    for index in range(len(bars)):
        if index + 1 < lookback:
            continue

        window = bars[index - lookback + 1:index + 1]
        highs[index] = max(bar.high_price for bar in window)
        lows[index] = min(bar.low_price for bar in window)

    return highs, lows


def _status_for_row(
    *,
    bar_count: int,
    values: dict[str, Decimal | None],
) -> tuple[str, tuple[str, ...]]:
    if bar_count < 5:
        return "INSUFFICIENT", REQUIRED_INDICATOR_FIELDS

    missing = tuple(
        name
        for name in REQUIRED_INDICATOR_FIELDS
        if values.get(name) is None
    )

    if not missing:
        return "READY", ()

    if all(values.get(name) is None for name in REQUIRED_INDICATOR_FIELDS):
        return "INSUFFICIENT", missing

    return "PARTIAL", missing


class IndicatorEngine:
    """일봉 기반 기술적 지표 계산기."""

    def calculate(
        self,
        bars: Sequence[PriceBar],
    ) -> list[DailyIndicator]:
        if not bars:
            return []

        ordered_bars = sorted(
            bars,
            key=lambda item: item.trade_date,
        )

        closes = [bar.close_price for bar in ordered_bars]
        volumes = [bar.volume for bar in ordered_bars]

        ma5 = _rolling_mean(closes, 5)
        ma20 = _rolling_mean(closes, 20)
        ma60 = _rolling_mean(closes, 60)
        volume_ma20 = _rolling_mean(volumes, 20)

        ema12 = _ema(closes, 12)
        ema26 = _ema(closes, 26)
        rsi14 = _rsi_wilder(closes, 14)

        macd, macd_signal, macd_histogram = _macd(
            closes
        )

        (
            bollinger_middle,
            bollinger_upper,
            bollinger_lower,
        ) = _bollinger(closes, 20)

        atr14 = _atr_wilder(ordered_bars, 14)
        high_52w, low_52w = _rolling_52w(ordered_bars)

        result: list[DailyIndicator] = []

        for index, bar in enumerate(ordered_bars):
            field_values = {
                "ma5": ma5[index],
                "ma20": ma20[index],
                "ma60": ma60[index],
                "ema12": ema12[index],
                "rsi14": rsi14[index],
                "volume_ma20": volume_ma20[index],
                "high_52w": high_52w[index],
                "low_52w": low_52w[index],
            }
            status_code, missing_fields = _status_for_row(
                bar_count=index + 1,
                values=field_values,
            )

            result.append(
                DailyIndicator(
                    trade_date=bar.trade_date,
                    close_price=bar.close_price,
                    volume=bar.volume,
                    ma5=ma5[index],
                    ma20=ma20[index],
                    ma60=ma60[index],
                    ema12=ema12[index],
                    ema26=ema26[index],
                    rsi14=rsi14[index],
                    macd=macd[index],
                    macd_signal=macd_signal[index],
                    macd_histogram=macd_histogram[index],
                    bollinger_middle=bollinger_middle[index],
                    bollinger_upper=bollinger_upper[index],
                    bollinger_lower=bollinger_lower[index],
                    atr14=atr14[index],
                    volume_ma20=volume_ma20[index],
                    high_52w=high_52w[index],
                    low_52w=low_52w[index],
                    status_code=status_code,
                    missing_fields=missing_fields,
                )
            )

        return result
