"""1D SMA Golden Cross evaluation — Strategy 17579 semantics mirror (SHADOW)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Sequence

from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
    CROSS_STATE_ABOVE_NO_NEW,
    CROSS_STATE_BELOW,
    CROSS_STATE_FRESH_CROSS,
    CROSS_STATE_INSUFFICIENT_HISTORY,
    LONG_MA_WINDOW,
    MIN_COMPLETED_BARS,
    SHORT_MA_WINDOW,
)

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class MaCrossEvaluation:
    symbol: str
    sma5: Decimal | None
    sma20: Decimal | None
    prev_sma5: Decimal | None
    prev_sma20: Decimal | None
    cross_state: str
    is_fresh_golden_cross: bool
    insufficient_history: bool


def _sma(values: Sequence[Decimal], window: int) -> Decimal | None:
    if len(values) < window or window <= 0:
        return None
    chunk = values[-window:]
    return sum(chunk, ZERO) / Decimal(window)


def evaluate_daily_ma_cross(
    *,
    symbol: str,
    closes: Sequence[Decimal],
    prev_sma5: Decimal | None = None,
    prev_sma20: Decimal | None = None,
) -> MaCrossEvaluation:
    """completed daily closes + optional rolling today close."""

    if len(closes) < MIN_COMPLETED_BARS:
        return MaCrossEvaluation(
            symbol=symbol,
            sma5=None,
            sma20=None,
            prev_sma5=prev_sma5,
            prev_sma20=prev_sma20,
            cross_state=CROSS_STATE_INSUFFICIENT_HISTORY,
            is_fresh_golden_cross=False,
            insufficient_history=True,
        )

    # 현재/직전 bar SMA — 마지막 close 포함 현재, 그 직전은 prev
    current_closes = list(closes)
    prev_closes = current_closes[:-1] if len(current_closes) > 1 else current_closes

    sma5 = _sma(current_closes, SHORT_MA_WINDOW)
    sma20 = _sma(current_closes, LONG_MA_WINDOW)
    p_sma5 = _sma(prev_closes, SHORT_MA_WINDOW) if prev_sma5 is None else prev_sma5
    p_sma20 = _sma(prev_closes, LONG_MA_WINDOW) if prev_sma20 is None else prev_sma20

    if sma5 is None or sma20 is None or p_sma5 is None or p_sma20 is None:
        return MaCrossEvaluation(
            symbol=symbol,
            sma5=sma5,
            sma20=sma20,
            prev_sma5=p_sma5,
            prev_sma20=p_sma20,
            cross_state=CROSS_STATE_INSUFFICIENT_HISTORY,
            is_fresh_golden_cross=False,
            insufficient_history=True,
        )

    fresh = p_sma5 <= p_sma20 and sma5 > sma20
    if fresh:
        cross_state = CROSS_STATE_FRESH_CROSS
    elif sma5 > sma20:
        cross_state = CROSS_STATE_ABOVE_NO_NEW
    else:
        cross_state = CROSS_STATE_BELOW

    return MaCrossEvaluation(
        symbol=symbol,
        sma5=sma5,
        sma20=sma20,
        prev_sma5=p_sma5,
        prev_sma20=p_sma20,
        cross_state=cross_state,
        is_fresh_golden_cross=fresh,
        insufficient_history=False,
    )


def build_signal_fingerprint(
    *,
    symbol: str,
    cross_day: date,
) -> str:
    return f"gc:{symbol.upper()}:{cross_day.isoformat()}"
