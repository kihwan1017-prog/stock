"""AUTO position CLOSE / residual / dust / exit-allocation integrity gates.

Canonical invariants (UBA AUTO):
- CLOSE only when remaining AUTO-owned qty ≈ 0, OR remaining is unsellable dust
  and AUTO_DUST provenance is recorded.
- Sellable residual must stay OPEN/PARTIAL_EXIT (never CLOSED).
- One exit fill quantity allocates at most once across bindings (FIFO take).
- Manual holdings are never part of AUTO-owned qty.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from stock_platform.broker.upbit.rules import UPBIT_MIN_NOTIONAL_KRW

ZERO = Decimal("0")
QTY_EPS = Decimal("0.00000001")
CloseDecision = Literal[
    "CLOSE_FLAT",
    "CLOSE_AS_AUTO_DUST",
    "KEEP_PARTIAL_EXIT",
    "KEEP_OPEN",
]

BINDING_STATUS_PARTIAL_EXIT = "PARTIAL_EXIT"


@dataclass(frozen=True, slots=True)
class ResidualCloseVerdict:
    decision: CloseDecision
    remaining_qty: Decimal
    estimated_value_krw: Decimal | None
    sellable_now: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "remaining_qty": str(self.remaining_qty),
            "estimated_value_krw": (
                str(self.estimated_value_krw)
                if self.estimated_value_krw is not None
                else None
            ),
            "sellable_now": self.sellable_now,
            "reason": self.reason,
        }


def qty_is_flat(qty: Decimal | None) -> bool:
    try:
        return Decimal(str(qty or 0)) <= QTY_EPS
    except Exception:  # noqa: BLE001
        return True


def estimate_notional(
    qty: Decimal,
    *,
    price: Decimal | None,
) -> Decimal | None:
    if price is None:
        return None
    try:
        px = Decimal(str(price))
        q = Decimal(str(qty))
    except Exception:  # noqa: BLE001
        return None
    if px <= ZERO or q <= ZERO:
        return ZERO
    return (q * px).quantize(Decimal("0.01"))


def classify_residual_for_close(
    remaining_qty: Decimal,
    *,
    mark_price: Decimal | None,
    min_notional: Decimal = UPBIT_MIN_NOTIONAL_KRW,
) -> ResidualCloseVerdict:
    """CLOSE 허용 여부 — min notional만으로 숨기지 않고 sellable 여부를 본다."""

    rem = Decimal(str(remaining_qty or 0))
    if rem <= QTY_EPS:
        return ResidualCloseVerdict(
            decision="CLOSE_FLAT",
            remaining_qty=ZERO,
            estimated_value_krw=ZERO,
            sellable_now=False,
            reason="REMAINING_FLAT",
        )

    value = estimate_notional(rem, price=mark_price)
    if value is None:
        # 가격 없으면 보수적으로 partial 유지 (잘못 CLOSED 금지)
        return ResidualCloseVerdict(
            decision="KEEP_PARTIAL_EXIT",
            remaining_qty=rem,
            estimated_value_krw=None,
            sellable_now=False,
            reason="MARK_PRICE_UNKNOWN_KEEP_PARTIAL",
        )

    sellable = value >= Decimal(str(min_notional))
    if sellable:
        return ResidualCloseVerdict(
            decision="KEEP_PARTIAL_EXIT",
            remaining_qty=rem,
            estimated_value_krw=value,
            sellable_now=True,
            reason="SELLABLE_RESIDUAL_BLOCK_CLOSE",
        )

    # 평가액 미달 → AUTO_DUST provenance 후 CLOSE 허용
    return ResidualCloseVerdict(
        decision="CLOSE_AS_AUTO_DUST",
        remaining_qty=rem,
        estimated_value_krw=value,
        sellable_now=False,
        reason="BELOW_MIN_NOTIONAL_AUTO_DUST",
    )


def build_auto_dust_record(
    *,
    qty: Decimal,
    estimated_value_krw: Decimal | None,
    reason: str,
    exit_order_id: int | None,
    symbol: str,
    binding_id: int | None = None,
) -> dict[str, Any]:
    return {
        "status": "AUTO_DUST",
        "symbol": str(symbol).upper(),
        "binding_id": binding_id,
        "owned_qty": str(qty),
        "estimated_value_krw": (
            str(estimated_value_krw) if estimated_value_krw is not None else None
        ),
        "reason": reason,
        "exit_order_id": int(exit_order_id) if exit_order_id is not None else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def exit_allocation_entries(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    raw = (meta or {}).get("exit_allocations")
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def allocated_qty_for_exit_order(
    meta: dict[str, Any] | None, *, exit_order_id: int
) -> Decimal:
    total = ZERO
    for row in exit_allocation_entries(meta):
        try:
            if int(row.get("order_id") or 0) != int(exit_order_id):
                continue
            total += Decimal(str(row.get("qty") or 0))
        except Exception:  # noqa: BLE001
            continue
    return total


def append_exit_allocation(
    meta: dict[str, Any],
    *,
    exit_order_id: int,
    qty: Decimal,
    fill_price: Decimal | None,
) -> dict[str, Any]:
    out = dict(meta or {})
    rows = exit_allocation_entries(out)
    rows.append(
        {
            "order_id": int(exit_order_id),
            "qty": str(qty),
            "fill_price": str(fill_price) if fill_price is not None else None,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    out["exit_allocations"] = rows
    return out


def incremental_exit_qty(
    *,
    cumulative_fill_qty: Decimal,
    already_allocated_on_binding: Decimal,
) -> Decimal:
    """Fill sync cumulative executed_volume → binding에 새로 배분할 증분."""

    cum = Decimal(str(cumulative_fill_qty or 0))
    prior = Decimal(str(already_allocated_on_binding or 0))
    inc = cum - prior
    if inc <= QTY_EPS:
        return ZERO
    return inc


def allocated_realized_from_orders(
    *,
    buy_filled_qty: Decimal,
    buy_filled_amount: Decimal,
    sell_filled_qty: Decimal,
    sell_filled_amount: Decimal,
    closed_qty: Decimal,
) -> tuple[Decimal, Decimal]:
    """부분/다중 binding 안전 PnL — closed_qty 비율로 buy/sell notional 배분.

    Returns (gross_realized, allocated_sell_amount).
    """

    cq = Decimal(str(closed_qty or 0))
    bq = Decimal(str(buy_filled_qty or 0))
    sq = Decimal(str(sell_filled_qty or 0))
    ba = Decimal(str(buy_filled_amount or 0))
    sa = Decimal(str(sell_filled_amount or 0))
    if cq <= QTY_EPS:
        return ZERO, ZERO
    buy_leg = ba * (cq / bq) if bq > QTY_EPS else ZERO
    sell_leg = sa * (cq / sq) if sq > QTY_EPS else ZERO
    return (sell_leg - buy_leg), sell_leg
