from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_UP, Decimal


ZERO = Decimal("0")
# 업비트 KRW 마켓 최소 주문 금액(원)
UPBIT_MIN_NOTIONAL_KRW = Decimal("5000")
# 업비트 수량 소수점 자리 (quantize 단위)
UPBIT_VOLUME_STEP = Decimal("0.00000001")


def upbit_tick_size(price: Decimal) -> Decimal:
    """
    업비트 KRW 호가 단위 (단순화 테이블).
    공식 규칙은 구간·종목별로 더 세분화될 수 있어 보수적으로 적용한다.
    """

    value = abs(price)
    if value < Decimal("10"):
        return Decimal("0.01")
    if value < Decimal("100"):
        return Decimal("0.1")
    if value < Decimal("1000"):
        return Decimal("1")
    if value < Decimal("10000"):
        return Decimal("5")
    if value < Decimal("100000"):
        return Decimal("10")
    if value < Decimal("500000"):
        return Decimal("50")
    if value < Decimal("1000000"):
        return Decimal("100")
    if value < Decimal("2000000"):
        return Decimal("500")
    return Decimal("1000")


def round_upbit_price(price: Decimal) -> Decimal:
    if price <= ZERO:
        return ZERO
    tick = upbit_tick_size(price)
    units = (price / tick).to_integral_value(rounding=ROUND_DOWN)
    # 소수점 호가 보존
    quantized = (units * tick)
    return quantized


def round_upbit_volume(volume: Decimal) -> Decimal:
    """업비트 수량은 소수점 허용 — 과도한 자리수만 자른다."""

    if volume <= ZERO:
        return ZERO
    return volume.quantize(UPBIT_VOLUME_STEP, rounding=ROUND_DOWN)


def volume_from_krw_buy_amount(
    *,
    amount: Decimal,
    price: Decimal,
    min_notional: Decimal = UPBIT_MIN_NOTIONAL_KRW,
) -> Decimal:
    """KRW BUY 금액→수량 (Decimal).

    requested_amount >= min 이면 final_qty * price 가
    requested_amount(및 min) 미만으로 떨어지지 않도록 수량 step ROUND_UP.
    requested_amount < min 이면 보정하지 않아 validate_upbit_notional 이 BLOCK.
    """

    amount_d = Decimal(str(amount))
    price_d = Decimal(str(price))
    min_d = Decimal(str(min_notional))
    if amount_d <= ZERO or price_d <= ZERO:
        return ZERO

    raw = amount_d / price_d
    if amount_d < min_d:
        # 최소금액 미만 요청은 임의로 5000원 주문으로 올리지 않음
        return raw.quantize(UPBIT_VOLUME_STEP, rounding=ROUND_DOWN)

    qty = raw.quantize(UPBIT_VOLUME_STEP, rounding=ROUND_UP)
    guard = 0
    # ROUND_UP 후에도 이론상 미달이면 step만 추가 (과도 증가 금지)
    while qty * price_d < amount_d and guard < 16:
        qty += UPBIT_VOLUME_STEP
        guard += 1
    while qty * price_d < min_d and guard < 32:
        qty += UPBIT_VOLUME_STEP
        guard += 1
    return qty


def validate_upbit_notional(
    *,
    side: str,
    order_type: str,
    quantity: Decimal,
    price: Decimal | None,
    market_krw_amount: Decimal | None = None,
) -> None:
    """최소 주문금액(KRW) 검증. 미달 시 ValueError."""

    side_u = side.upper()
    type_u = order_type.upper()
    notional = ZERO

    if type_u == "MARKET" and side_u == "BUY":
        # 시장가 매수: price 필드에 KRW 금액이 온다
        notional = market_krw_amount or price or ZERO
    elif price is not None and quantity > ZERO:
        notional = price * quantity
    elif market_krw_amount is not None:
        notional = market_krw_amount

    if notional > ZERO and notional < UPBIT_MIN_NOTIONAL_KRW:
        raise ValueError(
            f"Upbit minimum order amount is "
            f"{UPBIT_MIN_NOTIONAL_KRW} KRW "
            f"(got {notional})"
        )
