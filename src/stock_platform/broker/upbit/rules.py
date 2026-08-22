from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_UP, Decimal


ZERO = Decimal("0")
# 업비트 KRW 마켓 최소 주문 금액(원) — 프로젝트 SoT. 다른 모듈에 5000 하드코딩 금지.
UPBIT_MIN_NOTIONAL_KRW = Decimal("5000")
# persist 이전 차단 reason — 어댑터 ValueError와 동일 정책, 코드만 정규화
REASON_UPBIT_MIN_NOTIONAL_NOT_MET = "UPBIT_MIN_NOTIONAL_NOT_MET"
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


def round_upbit_krw_notional(amount: Decimal) -> Decimal:
    """MARKET BUY 총 KRW — 호가 tick 테이블 적용 금지. 원 단위 내림.

    의도 금액이 최소주문 이상이면 내림 후에도 최소 미만으로 떨어지지 않게 보정.
    """

    raw = Decimal(str(amount or 0))
    if raw <= ZERO:
        return ZERO
    quantized = raw.quantize(Decimal("1"), rounding=ROUND_DOWN)
    if quantized < UPBIT_MIN_NOTIONAL_KRW and raw >= UPBIT_MIN_NOTIONAL_KRW:
        return UPBIT_MIN_NOTIONAL_KRW
    return quantized


def round_upbit_price_up(price: Decimal) -> Decimal:
    """관측용 최소 매도 가능 지정가 — 호가를 올림. 주문가를 자동 변경하지 않는다."""

    if price <= ZERO:
        return ZERO
    tick = upbit_tick_size(price)
    units = (price / tick).to_integral_value(rounding=ROUND_UP)
    return units * tick


def minimum_sellable_limit_price(quantity: Decimal) -> Decimal | None:
    """보유 수량 Q로 최소 노셔널을 맞추는 지정가(호가 올림). 관측 전용."""

    qty = Decimal(str(quantity or 0))
    if qty <= ZERO:
        return None
    raw = UPBIT_MIN_NOTIONAL_KRW / qty
    return round_upbit_price_up(raw)


def compute_upbit_notional(
    *,
    side: str,
    order_type: str,
    quantity: Decimal,
    price: Decimal | None,
    market_krw_amount: Decimal | None = None,
) -> Decimal | None:
    """확정 가능한 KRW 노셔널. MARKET SELL 등 추정 불가하면 None (가격 추정 금지)."""

    side_u = str(side or "").upper()
    type_u = str(order_type or "").upper()
    qty = Decimal(str(quantity or 0))

    if type_u == "MARKET" and side_u == "BUY":
        amount = market_krw_amount if market_krw_amount is not None else price
        if amount is None:
            return None
        value = Decimal(str(amount))
        return value if value > ZERO else None
    if type_u == "MARKET" and side_u == "SELL":
        if market_krw_amount is not None:
            value = Decimal(str(market_krw_amount))
            return value if value > ZERO else None
        # 시장가 매도는 체결가 추정 금지
        return None
    if price is not None and qty > ZERO:
        value = Decimal(str(price)) * qty
        return value if value > ZERO else None
    if market_krw_amount is not None:
        value = Decimal(str(market_krw_amount))
        return value if value > ZERO else None
    return None


def evaluate_upbit_min_notional(
    *,
    broker_code: str,
    environment: str,
    side: str,
    order_type: str,
    quantity: Decimal,
    price: Decimal | None,
    market_krw_amount: Decimal | None = None,
) -> str | None:
    """PAPER·KIWOOM은 적용하지 않는다. 미달이면 UPBIT_MIN_NOTIONAL_NOT_MET."""

    env = str(environment or "").strip().upper()
    broker = str(broker_code or "").strip().upper()
    if env == "PAPER" or broker != "UPBIT":
        return None
    notional = compute_upbit_notional(
        side=side,
        order_type=order_type,
        quantity=quantity,
        price=price,
        market_krw_amount=market_krw_amount,
    )
    if notional is None:
        return None
    if notional < UPBIT_MIN_NOTIONAL_KRW:
        return REASON_UPBIT_MIN_NOTIONAL_NOT_MET
    return None


def describe_upbit_exit_notional(
    *,
    held_quantity: Decimal,
    current_price: Decimal | None,
) -> dict[str, str | bool | None]:
    """관측 전용 필드. 주문가를 바꾸지 않는다."""

    qty = Decimal(str(held_quantity or 0))
    price = (
        Decimal(str(current_price))
        if current_price is not None
        else None
    )
    current_notional = (
        str(qty * price) if price is not None and qty > ZERO else None
    )
    min_price = minimum_sellable_limit_price(qty)
    below = False
    if price is not None and qty > ZERO:
        below = (qty * price) < UPBIT_MIN_NOTIONAL_KRW
    return {
        "held_quantity": str(qty),
        "current_price": None if price is None else str(price),
        "current_notional": current_notional,
        "minimum_notional": str(UPBIT_MIN_NOTIONAL_KRW),
        "minimum_sellable_price": None if min_price is None else str(min_price),
        "below_minimum": below,
    }


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

    computed = compute_upbit_notional(
        side=side,
        order_type=order_type,
        quantity=quantity,
        price=price,
        market_krw_amount=market_krw_amount,
    )
    notional = computed if computed is not None else ZERO

    if notional > ZERO and notional < UPBIT_MIN_NOTIONAL_KRW:
        raise ValueError(
            f"Upbit minimum order amount is "
            f"{UPBIT_MIN_NOTIONAL_KRW} KRW "
            f"(got {notional})"
        )
