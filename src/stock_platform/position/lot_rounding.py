from __future__ import annotations

from decimal import ROUND_DOWN, Decimal


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


def round_price_to_tick(
    price: Decimal,
    *,
    round_down: bool = True,
) -> Decimal:
    if price <= ZERO:
        return ZERO
    tick = krx_tick_size(price)
    units = (price / tick).to_integral_value(
        rounding=ROUND_DOWN if round_down else ROUND_DOWN
    )
    return (units * tick).quantize(Decimal("1"))


def round_share_quantity(quantity: Decimal) -> Decimal:
    """국내 주식 수량은 1주 단위로 내림."""
    if quantity <= ZERO:
        return ZERO
    return quantity.to_integral_value(rounding=ROUND_DOWN)
