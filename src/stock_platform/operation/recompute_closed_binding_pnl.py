"""CLOSED binding realized_pnl 복구 — order filled_amount SoT (임의 추정 금지)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.strategy_owned_entities import (
    BINDING_STATUS_CLOSED,
    StrategyPositionBindingEntity,
)

ZERO = Decimal("0")
QUANT = Decimal("0.01")


def recompute_closed_binding_realized_from_orders(
    session: Session,
    *,
    user_broker_account_id: int | None = None,
    binding_ids: list[int] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """손실 미stamp(realized_pnl=0) CLOSED binding을 entry/exit order로 재산출.

    buy/sell filled_amount가 모두 있을 때만 갱신. 추정 quantity 금지.
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
        qty = Decimal(str(buy.filled_quantity or sell.filled_quantity or 0))
        if buy_amt <= ZERO or sell_amt <= ZERO:
            skipped.append(
                {
                    "binding_id": int(row.binding_id),
                    "reason": "HISTORICAL_AMOUNT_UNRECOVERABLE",
                    "buy_amount": str(buy_amt),
                    "sell_amount": str(sell_amt),
                }
            )
            continue

        new_gross = (sell_amt - buy_amt).quantize(QUANT)
        old_gross = Decimal(str(row.realized_pnl or 0)).quantize(QUANT)
        # 이미 일치하면 스킵 (정상 이익 거래 보존)
        if abs(old_gross - new_gross) <= Decimal("0.05"):
            # closed_quantity만 보강
            if qty > ZERO and meta.get("closed_quantity") is None:
                if not dry_run:
                    meta["closed_quantity"] = str(qty)
                    row.meta_json = meta
                updated.append(
                    {
                        "binding_id": int(row.binding_id),
                        "symbol": row.symbol,
                        "action": "META_CLOSED_QUANTITY_ONLY",
                        "quantity": str(qty),
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

        meta["closed_quantity"] = str(qty) if qty > ZERO else meta.get(
            "closed_quantity"
        )
        meta["realized_pnl_recomputed_from"] = "ORDER_FILLED_AMOUNT"
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
                "quantity": str(qty),
                "dry_run": dry_run,
            }
        )

    if not dry_run and updated:
        session.commit()

    return {
        "updated_count": len(
            [u for u in updated if u.get("action") != "META_CLOSED_QUANTITY_ONLY"]
        )
        + len(
            [u for u in updated if u.get("action") == "META_CLOSED_QUANTITY_ONLY"]
        ),
        "pnl_updated_count": len(
            [u for u in updated if "new_realized_pnl" in u]
        ),
        "skipped_count": len(skipped),
        "updated": updated,
        "skipped_sample": skipped[:20],
    }
