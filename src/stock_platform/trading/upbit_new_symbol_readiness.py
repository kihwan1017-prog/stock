"""UPBIT 신규 심볼 자동매매 준비 — Risk 값을 변경하지 않는 계산/판정."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from stock_platform.broker.upbit.rules import UPBIT_MIN_NOTIONAL_KRW
from stock_platform.ai.market_analysis.constants import MIN_DAILY_CANDLES


ZERO = Decimal("0")
# 3% SL 후에도 최소 노셔널 유지: 5000 / 0.97 ≈ 5155. 수수료·호가 여유 포함.
RECOMMENDED_SMOKE_MAX_ORDER_AMOUNT = Decimal("10000")
SL_RATIO = Decimal("0.03")


def classify_entry_positions(
    positions: list[dict[str, Any]],
    *,
    min_notional: Decimal = UPBIT_MIN_NOTIONAL_KRW,
) -> dict[str, Any]:
    """보유 행은 삭제하지 않는다. ENTRY cap 관측용 분류만."""

    held: list[dict[str, Any]] = []
    dust: list[dict[str, Any]] = []
    for row in positions:
        qty = Decimal(str(row.get("quantity") or 0))
        if qty <= ZERO:
            continue
        notional = Decimal(str(row.get("evaluation_amount") or 0))
        item = {
            "symbol": str(row.get("symbol") or "").upper(),
            "quantity": str(qty),
            "notional": str(notional),
            "counts_in_current_cap": True,
        }
        held.append(item)
        if notional < min_notional:
            dust.append(item)
    return {
        "position_count": len(held),
        "non_dust_count": len(held) - len(dust),
        "dust_count": len(dust),
        "dust_excluded_count_if_policy_b": len(held) - len(dust),
        "current_domain_counts_dust": True,
        "min_notional": str(min_notional),
        "positions": held,
        "dust_positions": dust,
    }


def recommended_max_order_amount(
    *,
    current_max_order_amount: Decimal,
    available_krw: Decimal | None,
) -> dict[str, Any]:
    candidates = (
        Decimal("7000"),
        Decimal("8000"),
        Decimal("10000"),
    )
    after_sl = {
        str(amount): str((amount * (Decimal("1") - SL_RATIO)).quantize(Decimal("1")))
        for amount in (current_max_order_amount, *candidates)
    }
    recommended = RECOMMENDED_SMOKE_MAX_ORDER_AMOUNT
    if available_krw is not None and available_krw < recommended:
        if available_krw >= Decimal("8000"):
            recommended = Decimal("8000")
        elif available_krw >= Decimal("7000"):
            recommended = Decimal("7000")
        else:
            recommended = current_max_order_amount
    current_after = Decimal(after_sl[str(current_max_order_amount)])
    return {
        "minimum_order": str(UPBIT_MIN_NOTIONAL_KRW),
        "current_max_order_amount": str(current_max_order_amount),
        "current_after_3pct_sl": str(current_after),
        "current_survives_3pct_sl": current_after >= UPBIT_MIN_NOTIONAL_KRW,
        "candidates_after_3pct_sl": after_sl,
        "recommended_test_notional": str(recommended),
        "recommended_max_order_amount": str(recommended),
        "auto_applied": False,
    }


def entry_blocked_by_position_cap(
    *,
    position_count: int,
    max_position_count: int,
) -> bool:
    return int(position_count) >= int(max_position_count)


def classify_official_daily_history(
    bar_count: int,
    *,
    warmup_bars: int = 20,
) -> str:
    """공식 일봉 분류. warmup은 전략 long_window, 30일은 market analysis SoT."""

    count = int(bar_count)
    if count < int(warmup_bars):
        return "WARMUP_INSUFFICIENT"
    if count < int(MIN_DAILY_CANDLES):
        return "SHORT_HISTORY"
    return "BACKTEST_DATA_READY"
