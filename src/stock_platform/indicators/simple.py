"""단순 시계열 헬퍼 (단위 테스트·레거시 STEP34 호환).

본선 지표 엔진은 `stock_platform.indicators` 를 사용한다.
"""

from collections.abc import Sequence


def sma(values: Sequence[float], period: int) -> float | None:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return None
    selected = values[-period:]
    return sum(selected) / period


def ema(values: Sequence[float], period: int) -> float | None:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    current = sum(values[:period]) / period
    for value in values[period:]:
        current = (value - current) * multiplier + current
    return current


def rsi(values: Sequence[float], period: int = 14) -> float | None:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) <= period:
        return None
    changes = [
        current - previous
        for previous, current in zip(values[:-1], values[1:])
    ]
    recent = changes[-period:]
    average_gain = sum(max(change, 0) for change in recent) / period
    average_loss = sum(max(-change, 0) for change in recent) / period
    if average_loss == 0:
        return 100.0
    rs = average_gain / average_loss
    return 100 - (100 / (1 + rs))
