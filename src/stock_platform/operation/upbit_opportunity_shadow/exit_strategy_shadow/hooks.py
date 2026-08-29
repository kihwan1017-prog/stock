"""Exit strategy shadow hooks — fail-open, never blocks REAL."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog

from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.service import (
    enroll_on_natural_entry,
    finalize_actual_exit,
    observe_price_for_entry,
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
    deployment_id: int | None = None,
    broker_order_uuid: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    if entry_order_id is None:
        return {"ok": False, "reason": "NO_ENTRY_ORDER"}
    try:
        return enroll_on_natural_entry(
            session,
            user_broker_account_id=user_broker_account_id,
            symbol=symbol,
            entry_order_id=int(entry_order_id),
            entry_at=entry_at,
            entry_price=entry_price,
            entry_qty=entry_quantity,
            entry_fee=entry_fee,
            binding_id=binding_id,
            strategy_id=strategy_id,
            deployment_id=deployment_id,
            broker_order_uuid=broker_order_uuid,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "exit_strategy_shadow_enroll_failed",
            binding_id=binding_id,
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}


def finalize_binding_on_close(
    session: Any,
    *,
    binding_id: int | None = None,
    entry_order_id: int | None = None,
    exit_reason: str | None,
    exit_at: Any,
    exit_price: Decimal | None,
    exit_order_id: int | None = None,
    actual_net_pnl: float | None = None,
) -> dict[str, Any]:
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    try:
        from decimal import Decimal as Dec

        return finalize_actual_exit(
            session,
            entry_order_id=entry_order_id,
            binding_id=binding_id,
            exit_reason=exit_reason,
            exit_at=exit_at,
            exit_price=exit_price,
            exit_order_id=exit_order_id,
            actual_net_pnl=(
                D(str(actual_net_pnl)) if actual_net_pnl is not None else None
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "exit_strategy_shadow_finalize_failed",
            binding_id=binding_id,
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}


def observe_entry_price(
    session: Any,
    *,
    entry_order_id: int,
    price: Decimal,
    observed_at: Any = None,
    short_ma: Decimal | None = None,
    long_ma: Decimal | None = None,
) -> dict[str, Any]:
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    try:
        return observe_price_for_entry(
            session,
            entry_order_id=entry_order_id,
            price=price,
            observed_at=observed_at,
            short_ma=short_ma,
            long_ma=long_ma,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "exit_strategy_shadow_observe_failed",
            entry_order_id=entry_order_id,
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}
