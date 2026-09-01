"""Fail-open hooks — REAL trading path side-effect 0."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)


def enroll_binding_on_open(
    session: Session,
    *,
    user_broker_account_id: int,
    binding_id: int,
    symbol: str,
    strategy_id: int | None,
    entry_order_id: int | None,
    entry_at: datetime,
    entry_price: Decimal,
    entry_quantity: Decimal | None = None,
    entry_fee: Decimal | None = None,
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.service import (
        enroll_on_position_open,
        shadow_enabled,
    )

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
        logger.warning("eosv3_enroll_failed", binding_id=binding_id, error=str(exc)[:200])
        return {"ok": False, "error": type(exc).__name__}


def finalize_binding_on_close(
    session: Session,
    *,
    binding_id: int,
    exit_reason: str | None,
    exit_at: datetime | None,
    exit_price: Decimal | None,
    gross_pnl: float | None = None,
    fee: float | None = None,
    net_pnl: float | None = None,
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.service import (
        finalize_baseline_on_binding_close,
        shadow_enabled,
    )

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
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("eosv3_finalize_failed", binding_id=binding_id, error=str(exc)[:200])
        return {"ok": False, "error": type(exc).__name__}


def observe_binding_price(
    session: Session,
    *,
    binding_id: int,
    price: Decimal,
    observed_at: datetime | None = None,
    quantity: Decimal | None = None,
) -> dict[str, Any]:
    from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.service import (
        observe_price_tick,
        shadow_enabled,
    )

    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    try:
        return observe_price_tick(
            session,
            binding_id=binding_id,
            price=price,
            observed_at=observed_at,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("eosv3_observe_failed", binding_id=binding_id, error=str(exc)[:200])
        return {"ok": False, "error": type(exc).__name__}
