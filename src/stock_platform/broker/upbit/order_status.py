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


def upbit_fill_summary(remote: dict[str, Any]) -> dict[str, Any]:
    """체결 요약 (Decimal 문자열)."""

    executed = _dec(remote.get("executed_volume"))
    trades = remote.get("trades") if isinstance(remote.get("trades"), list) else []
    funds = ZERO
    volume = ZERO
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        funds += _dec(trade.get("funds"))
        volume += _dec(trade.get("volume"))
    avg = ZERO
    if volume > ZERO:
        avg = funds / volume
    elif executed > ZERO and remote.get("avg_price") not in (None, ""):
        avg = _dec(remote.get("avg_price"))
    elif executed > ZERO and trades:
        avg = _dec(trades[0].get("price"))
    return {
        "executed_volume": executed,
        "avg_price": avg,
        "paid_fee": _dec(remote.get("paid_fee")),
        "trades_count": int(remote.get("trades_count") or len(trades) or 0),
        "funds": funds,
        "state": str(remote.get("state") or ""),
    }
