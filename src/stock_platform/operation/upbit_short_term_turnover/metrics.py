"""Cost-aware research metrics (no lookahead)."""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class RoundTripCost:
    """왕복 수수료·슬리피지 분리."""

    buy_fee: Decimal
    sell_fee: Decimal
    slippage: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal

    @property
    def fee_total(self) -> Decimal:
        return self.buy_fee + self.sell_fee


def apply_round_trip_costs(
    *,
    entry_price: Decimal,
    exit_price: Decimal,
    notional_krw: Decimal,
    fee_rate: Decimal,
    slippage_bps_each_side: Decimal = Decimal("2"),
) -> RoundTripCost:
    """BUY/SELL fee + 양측 slippage(bps) → gross/net 분리."""

    if entry_price <= 0 or notional_krw <= 0:
        zero = Decimal("0")
        return RoundTripCost(zero, zero, zero, zero, zero)

    qty = notional_krw / entry_price
    buy_notional = entry_price * qty
    sell_notional = exit_price * qty
    buy_fee = buy_notional * fee_rate
    sell_fee = sell_notional * fee_rate
    # 슬리피지: 명목 금액 × bps/10000 × 2(왕복)
    slip = notional_krw * (slippage_bps_each_side / Decimal("10000")) * Decimal("2")
    gross = sell_notional - buy_notional
    net = gross - buy_fee - sell_fee - slip
    return RoundTripCost(
        buy_fee=buy_fee,
        sell_fee=sell_fee,
        slippage=slip,
        gross_pnl=gross,
        net_pnl=net,
    )


def profit_factor(nets: Sequence[float]) -> float:
    """승 합 / |패 합|. 손실 없으면 승만 있으면 큰 값."""

    win = sum(n for n in nets if n > 0)
    loss = abs(sum(n for n in nets if n < 0))
    if loss <= 0:
        return 999.0 if win > 0 else 0.0
    return float(win / loss)


def max_drawdown(nets: Sequence[float]) -> float:
    """누적 순손익 경로의 peak-to-trough MDD (양수)."""

    equity = 0.0
    peak = 0.0
    mdd = 0.0
    for n in nets:
        equity += float(n)
        peak = max(peak, equity)
        mdd = max(mdd, peak - equity)
    return mdd


def trades_per_day_stats(
    entry_ats: Iterable[datetime],
    *,
    window_days: int,
) -> dict[str, float | int | None]:
    """일별 거래수 분포 (median/p25/p75/zero-trade days)."""

    by_day: Counter[date] = Counter()
    for at in entry_ats:
        by_day[at.date()] += 1
    days = max(int(window_days), 1)
    counts = [float(by_day.get(d, 0)) for d in by_day]
    # zero-trade days = window - active days (근사)
    zero_days = max(0, days - len(by_day))
    all_day_counts = counts + [0.0] * zero_days
    if not all_day_counts:
        return {
            "mean": 0.0,
            "median": 0.0,
            "p25": 0.0,
            "p75": 0.0,
            "zero_trade_days_pct": 100.0,
            "active_days": 0,
        }

    def _pct(xs: list[float], q: float) -> float:
        if not xs:
            return 0.0
        ordered = sorted(xs)
        idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
        return float(ordered[idx])

    return {
        "mean": float(statistics.fmean(all_day_counts)),
        "median": float(statistics.median(all_day_counts)),
        "p25": _pct(all_day_counts, 0.25),
        "p75": _pct(all_day_counts, 0.75),
        "zero_trade_days_pct": round(100.0 * zero_days / days, 1),
        "active_days": len(by_day),
    }
