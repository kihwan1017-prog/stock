"""Upbit 원격 주문 상태 → 도메인 OrderStatus 정규화 (STEP 10-1)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from stock_platform.order.models import OrderStatus

ZERO = Decimal("0")


def _dec(value: Any) -> Decimal:
    if value in (None, ""):
        return ZERO
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return ZERO


def normalize_upbit_order_status(remote: dict[str, Any]) -> OrderStatus | None:
    """Upbit /v1/order 응답을 도메인 상태로 정규화.

    규칙:
    - done + executed>0 → FILLED
    - cancel + executed>0 → FILLED  (시장가 잔여 KRW 취소 포함 체결 완료)
    - cancel + executed=0 → CANCELLED
    - wait/watch + executed>0 → PARTIALLY_FILLED
    - wait/watch + executed=0 → ACCEPTED
    """

    if not isinstance(remote, dict):
        return None
    state = str(remote.get("state") or "").strip().lower()
    executed = _dec(remote.get("executed_volume"))
    remaining = remote.get("remaining_volume")
    remaining_d = (
        None if remaining in (None, "") else _dec(remaining)
    )

    if state in {"wait", "watch"}:
        if executed > ZERO:
            return OrderStatus.PARTIALLY_FILLED
        return OrderStatus.ACCEPTED

    if state == "done":
        if executed > ZERO:
            # 잔량이 명시적으로 남아 있으면 부분체결
            if remaining_d is not None and remaining_d > ZERO:
                return OrderStatus.PARTIALLY_FILLED
            return OrderStatus.FILLED
        return OrderStatus.FILLED

    if state in {"cancel", "cancelled"}:
        if executed > ZERO:
            # 잔여 취소가 포함된 체결 완료 — 후속 Post-fill 필수
            return OrderStatus.FILLED
        return OrderStatus.CANCELLED

    return None


def _dec_str(value: Decimal) -> str:
    """JSON/metadata용 — 과학적 표기 방지."""

    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def upbit_fill_summary(remote: dict[str, Any]) -> dict[str, Any]:
    """체결 요약 (Decimal).

    정책:
    - average_fill_price = Σ(price×volume) / Σ(volume)  (fee 제외)
    - filled funds = Σ(trade.funds) 또는 Σ(price×volume)
    - Upbit 응답의 avg_price는 fee 포함일 수 있어 사용하지 않음
    - trades[]가 없고 limit이면 unit price 필드를 fallback
    """

    executed = _dec(remote.get("executed_volume"))
    paid_fee = _dec(remote.get("paid_fee"))
    trades = remote.get("trades") if isinstance(remote.get("trades"), list) else []

    notional = ZERO
    volume = ZERO
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        price = _dec(trade.get("price"))
        vol = _dec(trade.get("volume"))
        funds_t = _dec(trade.get("funds"))
        if vol <= ZERO:
            continue
        volume += vol
        if funds_t > ZERO:
            notional += funds_t
        else:
            notional += price * vol

    avg = ZERO
    funds = notional
    if volume > ZERO:
        avg = notional / volume
    elif executed > ZERO:
        # trades 누락 — Upbit avg_price(fee 포함 가능)는 절대 사용하지 않음
        ord_type = str(remote.get("ord_type") or "").strip().lower()
        unit = _dec(remote.get("price"))
        if ord_type == "limit" and unit > ZERO:
            avg = unit
            funds = executed * unit

    return {
        "executed_volume": executed,
        "avg_price": avg,
        "paid_fee": paid_fee,
        "trades_count": int(remote.get("trades_count") or len(trades) or 0),
        "funds": funds,
        "state": str(remote.get("state") or ""),
        "has_trades": bool(trades) and volume > ZERO,
    }
