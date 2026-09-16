"""Hooks — attach forward shadow after entry telemetry (fail-open)."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
    SymbolEntrySnapshot,
)

logger = logging.getLogger(__name__)


def maybe_enroll_entry_signal_shadow(
    *,
    uba_id: int,
    symbol: str,
    short_ma: Decimal | None,
    long_ma: Decimal | None,
    snap: SymbolEntrySnapshot | None,
    decision: str,
    block_reason: str | None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Called from ma_evaluator after bullish evaluate — NEVER blocks REAL path."""

    try:
        from stock_platform.common.settings import get_settings

        if not bool(
            getattr(get_settings(), "upbit_entry_signal_shadow_enabled", True)
        ):
            return {"ok": False, "reason": "DISABLED"}
        if short_ma is None or long_ma is None:
            return {"ok": False, "reason": "NO_MA"}
        emit_suppressed = str(block_reason or "") == "SIGNAL_EMIT_SUPPRESSED"
        from stock_platform.database.session import get_session_factory
        from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.service import (
            enroll_forward_observation,
        )

        sf = get_session_factory()
        session = sf()
        try:
            result = enroll_forward_observation(
                session,
                uba_id=int(uba_id),
                symbol=str(symbol).upper(),
                selection_id=(
                    int(snap.selection_id)
                    if snap and snap.selection_id
                    else None
                ),
                short_ma=short_ma,
                long_ma=long_ma,
                snap=snap,
                emit_suppressed=emit_suppressed,
                commit=True,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.warning(
                "entry_signal_shadow_enroll_failed",
                extra={"error": type(exc).__name__, "uba": uba_id},
            )
            return {"ok": False, "error": type(exc).__name__}
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "entry_signal_shadow_hook_failed",
            extra={"error": type(exc).__name__},
        )
        return {"ok": False, "error": type(exc).__name__}
