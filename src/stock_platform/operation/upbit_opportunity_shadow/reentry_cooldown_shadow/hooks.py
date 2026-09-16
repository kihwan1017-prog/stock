"""Re-entry cooldown shadow hooks — fail-open, REAL 무영향."""

from __future__ import annotations

from typing import Any

import structlog

from stock_platform.operation.upbit_opportunity_shadow.reentry_cooldown_shadow.service import (
    finalize_reentry_outcome,
    observe_reentry_on_new_entry,
)

logger = structlog.get_logger(__name__)


def enroll_reentry_on_open(
    session: Any,
    *,
    user_broker_account_id: int,
    symbol: str,
    entry_order_id: int | None,
    entry_at: Any,
) -> dict[str, Any]:
    try:
        return observe_reentry_on_new_entry(
            session,
            user_broker_account_id=user_broker_account_id,
            symbol=symbol,
            new_entry_order_id=entry_order_id,
            new_entry_at=entry_at,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "reentry_cooldown_shadow_enroll_failed",
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}


def finalize_reentry_on_close(
    session: Any,
    *,
    entry_order_id: int | None,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    try:
        return finalize_reentry_outcome(
            session,
            entry_order_id=entry_order_id,
            user_broker_account_id=user_broker_account_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "reentry_cooldown_shadow_finalize_failed",
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}
