from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from stock_platform.broker.upbit.rules import (
    round_upbit_price,
    round_upbit_volume,
    upbit_tick_size,
)


ZERO = Decimal("0")


def krx_tick_size(price: Decimal) -> Decimal:
    """KRX 보통주 호가단위(단순화 테이블)."""
    value = abs(price)
    if value < Decimal("2000"):
        return Decimal("1")
    if value < Decimal("5000"):
        return Decimal("5")
    if value < Decimal("20000"):
        return Decimal("10")
    if value < Decimal("50000"):
        return Decimal("50")
    if value < Decimal("200000"):
        return Decimal("100")
    if value < Decimal("500000"):
        return Decimal("500")
    return Decimal("1000")


def is_krx_tick_aligned(price: Decimal) -> bool:
    """지정가가 로컬 KRX 호가단위 배수인지. broker REST 없음."""
    value = Decimal(str(price))
    if value <= ZERO:
        return False
    tick = krx_tick_size(value)
    return (value % tick) == ZERO


def tick_size_for_exchange(
    exchange_code: str,
    price: Decimal,
) -> Decimal:
    code = (exchange_code or "").upper()
    if code in {"UPBIT", "CRYPTO"}:
        return upbit_tick_size(price)
    return krx_tick_size(price)


def round_price_to_tick(
    price: Decimal,
    *,
    round_down: bool = True,
    exchange_code: str = "KRX",
) -> Decimal:
    if price <= ZERO:
        return ZERO
    tick = tick_size_for_exchange(exchange_code, price)
    units = (price / tick).to_integral_value(
        rounding=ROUND_DOWN if round_down else ROUND_DOWN
    )
    return units * tick


def round_share_quantity(
    quantity: Decimal,
    *,
    exchange_code: str = "KRX",
) -> Decimal:
    """국내 주식은 1주, 업비트는 소수 수량."""
    if quantity <= ZERO:
        return ZERO
    if (exchange_code or "").upper() in {"UPBIT", "CRYPTO"}:
        return round_upbit_volume(quantity)
    return quantity.to_integral_value(rounding=ROUND_DOWN)
