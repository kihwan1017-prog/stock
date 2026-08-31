"""Trailing forward shadow hooks — REAL path side-effect only (fail-open)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog

from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.service import (
    enroll_on_position_open,
    finalize_baseline_on_binding_close,
    observe_price_tick,
    shadow_enabled,
)

logger = structlog.get_logger(__name__)


def enroll_binding_on_open(
    session: Any,
    *,
    user_broker_account_id: int,
    binding_id: int,
    symbol: str,
    strategy_id: int | None,
    entry_order_id: int | None,
    entry_at: Any,
    entry_price: Decimal,
    entry_quantity: Decimal | None = None,
    entry_fee: Decimal | None = None,
) -> dict[str, Any]:
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    try:
        return enroll_on_position_open(
            session,
            user_broker_account_id=user_broker_account_id,
            binding_id=binding_id,
            symbol=symbol,
            strategy_id=strategy_id,
            entry_order_id=entry_order_id,
            entry_at=entry_at,
            entry_price=entry_price,
            entry_quantity=entry_quantity,
            entry_fee=entry_fee,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "trailing_forward_shadow_enroll_failed",
            binding_id=binding_id,
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}


def finalize_binding_on_close(
    session: Any,
    *,
    binding_id: int,
    exit_reason: str | None,
    exit_at: Any,
    exit_price: Decimal | None,
    gross_pnl: float | None = None,
    fee: float | None = None,
    net_pnl: float | None = None,
    entry_order_id: int | None = None,
) -> dict[str, Any]:
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    try:
        return finalize_baseline_on_binding_close(
            session,
            binding_id=binding_id,
            exit_reason=exit_reason,
            exit_at=exit_at,
            exit_price=exit_price,
            gross_pnl=gross_pnl,
            fee=fee,
            net_pnl=net_pnl,
            entry_order_id=entry_order_id,
            resolve_ledger=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "trailing_forward_shadow_finalize_failed",
            binding_id=binding_id,
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}


def observe_binding_price(
    session: Any,
    *,
    binding_id: int,
    price: Decimal,
    observed_at: Any = None,
    quantity: Decimal | None = None,
) -> dict[str, Any]:
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    try:
        return observe_price_tick(
            session,
            binding_id=binding_id,
            price=price,
            observed_at=observed_at,
            quantity=quantity,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "trailing_forward_shadow_observe_failed",
            binding_id=binding_id,
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}
