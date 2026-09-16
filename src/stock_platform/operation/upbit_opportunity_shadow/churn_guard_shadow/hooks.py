"""Churn Guard Shadow hooks — fail-open toward trading."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def observe_churn_on_binding_closed(
    session: Any,
    *,
    user_broker_account_id: int,
    symbol: str,
    binding_id: int | None = None,
) -> dict[str, Any]:
    try:
        from stock_platform.operation.upbit_opportunity_shadow.churn_guard_shadow.service import (
            evaluate_on_binding_closed,
        )

        return evaluate_on_binding_closed(
            session,
            user_broker_account_id=int(user_broker_account_id),
            symbol=str(symbol),
            binding_id=binding_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "churn_guard_shadow_observe_failed",
            error=str(exc)[:240],
            uba=user_broker_account_id,
            symbol=symbol,
        )
        return {"ok": False, "error": str(exc)[:240], "fail_open": True}
