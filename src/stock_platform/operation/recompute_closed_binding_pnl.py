"""CLOSED binding realized_pnl 복구 — order filled_amount SoT (임의 추정 금지).

Partial exit / multi-binding 동일 exit_order 배분 시
sell_amt - buy_amt 전액 중복 반영을 금지한다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.position_close_integrity import (
    allocated_realized_from_orders,
)
from stock_platform.risk_engine.strategy_owned_entities import (
    BINDING_STATUS_CLOSED,
    StrategyPositionBindingEntity,
)

ZERO = Decimal("0")
QUANT = Decimal("0.01")
QTY_EPS = Decimal("0.00000001")


def recompute_closed_binding_realized_from_orders(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
    binding_ids: list[int] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """손실 미stamp CLOSED binding을 entry/exit order로 재산출.

    closed_quantity(또는 buy/sell min) 비율로 notional을 배분한다.
    historical rewrite는 호출자가 dry_run/명시적 실행으로만.
    """

    stmt = select(StrategyPositionBindingEntity).where(
        StrategyPositionBindingEntity.status == BINDING_STATUS_CLOSED
    )
    if user_broker_account_id is not None:
        stmt = stmt.where(
            StrategyPositionBindingEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    if binding_ids:
        stmt = stmt.where(
            StrategyPositionBindingEntity.binding_id.in_(
                [int(x) for x in binding_ids]
            )
        )

    rows = list(session.scalars(stmt))
    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for row in rows:
        meta = dict(row.meta_json or {})
        exit_oid = meta.get("exit_order_id")
        entry_oid = row.entry_order_id
        if entry_oid is None or exit_oid is None:
            skipped.append(
                {
                    "binding_id": int(row.binding_id),
                    "reason": "MISSING_ORDER_IDS",
                }
            )
            continue

        buy = session.get(TradingOrderEntity, int(entry_oid))
        sell = session.get(TradingOrderEntity, int(exit_oid))
        if buy is None or sell is None:
            skipped.append(
                {
                    "binding_id": int(row.binding_id),
                    "reason": "ORDER_NOT_FOUND",
                }
            )
            continue

        buy_amt = Decimal(str(buy.filled_amount or 0))
        sell_amt = Decimal(str(sell.filled_amount or 0))
        buy_qty = Decimal(str(buy.filled_quantity or 0))
        sell_qty = Decimal(str(sell.filled_quantity or 0))
        closed_qty = Decimal(str(meta.get("closed_quantity") or 0))
        if closed_qty <= QTY_EPS:
            # allocation 합이 있으면 우선
            allocs = meta.get("exit_allocations")
            if isinstance(allocs, list):
                for a in allocs:
                    if not isinstance(a, dict):
                        continue
                    try:
                        if int(a.get("order_id") or 0) == int(exit_oid):
                            closed_qty += Decimal(str(a.get("qty") or 0))
                    except Exception:  # noqa: BLE001
                        continue
        if closed_qty <= QTY_EPS:
            # 최후: min(buy,sell) — 동일 exit 다중 binding이면 과대 가능 → 경고
            closed_qty = min(buy_qty, sell_qty) if buy_qty > ZERO and sell_qty > ZERO else ZERO
            meta["closed_quantity_inferred"] = True

        if buy_amt <= ZERO or sell_amt <= ZERO or closed_qty <= QTY_EPS:
            skipped.append(
                {
                    "binding_id": int(row.binding_id),
                    "reason": "HISTORICAL_AMOUNT_UNRECOVERABLE",
                    "buy_amount": str(buy_amt),
                    "sell_amount": str(sell_amt),
                    "closed_qty": str(closed_qty),
                }
            )
            continue

        new_gross, _alloc_sell = allocated_realized_from_orders(
            buy_filled_qty=buy_qty,
            buy_filled_amount=buy_amt,
            sell_filled_qty=sell_qty,
            sell_filled_amount=sell_amt,
            closed_qty=closed_qty,
        )
        new_gross = new_gross.quantize(QUANT)
        old_gross = Decimal(str(row.realized_pnl or 0)).quantize(QUANT)
        if abs(old_gross - new_gross) <= Decimal("0.05"):
            if meta.get("closed_quantity") is None and closed_qty > ZERO:
                if not dry_run:
                    meta["closed_quantity"] = str(closed_qty)
                    row.meta_json = meta
                updated.append(
                    {
                        "binding_id": int(row.binding_id),
                        "symbol": row.symbol,
                        "action": "META_CLOSED_QUANTITY_ONLY",
                        "quantity": str(closed_qty),
                        "dry_run": dry_run,
                    }
                )
            else:
                skipped.append(
                    {
                        "binding_id": int(row.binding_id),
                        "reason": "ALREADY_MATCHES",
                    }
                )
            continue

        meta["closed_quantity"] = str(closed_qty)
        meta["realized_pnl_recomputed_from"] = "ALLOCATED_ORDER_FILLED_AMOUNT"
        meta["realized_pnl_before_recompute"] = str(old_gross)
        if not dry_run:
            row.realized_pnl = new_gross
            row.meta_json = meta
        updated.append(
            {
                "binding_id": int(row.binding_id),
                "symbol": row.symbol,
                "old_realized_pnl": str(old_gross),
                "new_realized_pnl": str(new_gross),
                "buy_amount": str(buy_amt),
                "sell_amount": str(sell_amt),
                "closed_qty": str(closed_qty),
                "dry_run": dry_run,
            }
        )

    if not dry_run and updated:
        session.commit()

    return {
        "updated_count": len(updated),
        "pnl_updated_count": len(
            [u for u in updated if "new_realized_pnl" in u]
        ),
        "skipped_count": len(skipped),
        "updated": updated,
        "skipped": skipped,
    }
