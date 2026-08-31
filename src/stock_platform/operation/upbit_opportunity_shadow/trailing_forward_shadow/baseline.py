"""Canonical baseline outcome resolver for trailing forward shadow.

REAL baseline SoT = strategy_position_binding + binding_closed_trade_metrics.
Identity join key = entry_order_id (+ UBA) — NOT upbit_strategy_position_binding.binding_id.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.autotrading_performance_service import (
    binding_closed_trade_metrics,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.strategy_owned_entities import (
    StrategyPositionBindingEntity,
)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_risk_binding_by_entry_order(
    session: Session,
    *,
    entry_order_id: int | None,
    user_broker_account_id: int | None = None,
) -> StrategyPositionBindingEntity | None:
    """entry_order_id로 risk ledger binding 조회 (canonical identity)."""

    if entry_order_id is None:
        return None
    q = select(StrategyPositionBindingEntity).where(
        StrategyPositionBindingEntity.entry_order_id == int(entry_order_id)
    )
    if user_broker_account_id is not None:
        q = q.where(
            StrategyPositionBindingEntity.user_broker_account_id
            == int(user_broker_account_id)
        )
    rows = list(session.scalars(q.order_by(StrategyPositionBindingEntity.binding_id.desc())))
    if not rows:
        return None
    # CLOSED 우선, 없으면 최신
    closed = [r for r in rows if str(r.status or "").upper() == "CLOSED"]
    return closed[0] if closed else rows[0]


def resolve_baseline_outcome_for_entry(
    session: Session,
    *,
    entry_order_id: int | None,
    user_broker_account_id: int | None = None,
    fallback_exit_reason: str | None = None,
    fallback_exit_at: datetime | None = None,
    fallback_exit_price: Decimal | None = None,
) -> dict[str, Any] | None:
    """Canonical REAL baseline outcome — 새 PnL 공식 금지."""

    binding = resolve_risk_binding_by_entry_order(
        session,
        entry_order_id=entry_order_id,
        user_broker_account_id=user_broker_account_id,
    )
    if binding is None:
        return None
    if str(binding.status or "").upper() != "CLOSED":
        return {
            "ok": False,
            "reason": "RISK_BINDING_NOT_CLOSED",
            "risk_binding_id": int(binding.binding_id),
            "entry_order_id": int(entry_order_id) if entry_order_id else None,
        }

    meta = dict(binding.meta_json or {})
    exit_oid = meta.get("exit_order_id")
    exit_order = None
    if exit_oid is not None:
        exit_order = session.get(TradingOrderEntity, int(exit_oid))

    metrics = binding_closed_trade_metrics(binding, exit_order=exit_order)
    exit_px = metrics.get("exit_price")
    if exit_px is None and fallback_exit_price is not None:
        exit_px = str(fallback_exit_price)

    exit_at = _as_utc(binding.closed_at) or _as_utc(fallback_exit_at)
    exit_reason = (
        metrics.get("exit_reason_raw")
        or fallback_exit_reason
        or metrics.get("exit_reason_category")
        or "UNKNOWN"
    )

    return {
        "ok": True,
        "DATA_SOURCE": "strategy_position_binding+binding_closed_trade_metrics",
        "risk_binding_id": int(binding.binding_id),
        "entry_order_id": metrics.get("entry_order_id") or entry_order_id,
        "exit_order_id": metrics.get("exit_order_id"),
        "symbol": metrics.get("symbol"),
        "entry_price": metrics.get("entry_price"),
        "entry_qty": metrics.get("quantity"),
        "exit_price": exit_px,
        "exit_reason": str(exit_reason)[:64],
        "exit_at": exit_at.isoformat() if exit_at else None,
        "exit_at_dt": exit_at,
        "gross_pnl": float(Decimal(str(metrics["gross_pnl"]))),
        "fee": float(Decimal(str(metrics["fees"]))),
        "net_pnl": float(Decimal(str(metrics["net_pnl"]))),
        "return_pct": float(Decimal(str(metrics["return_pct"]))),
        "holding_seconds": metrics.get("duration_sec"),
    }
