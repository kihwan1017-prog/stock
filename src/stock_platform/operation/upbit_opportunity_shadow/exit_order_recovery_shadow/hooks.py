"""Exit order recovery shadow hooks — fail-open toward REAL trading."""

from __future__ import annotations

from typing import Any

import structlog

from stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.service import (
    enroll_exit_order,
    shadow_enabled,
)

logger = structlog.get_logger(__name__)


def on_exit_order_submitted(
    session: Any,
    *,
    order_id: int | None,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    """Called after REAL exit submit success — never raises into REAL path."""

    if order_id is None:
        return {"ok": False, "reason": "NO_ORDER_ID"}
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    try:
        return enroll_exit_order(
            session,
            order_id=int(order_id),
            user_broker_account_id=user_broker_account_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "exit_order_recovery_shadow_enroll_failed",
            order_id=order_id,
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200], "REAL_TRADING_BLOCKED": False}
