"""Hooks — KIWOOM Golden Cross shadow (fail-open, REAL path 불변)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


def maybe_enroll_kiwoom_golden_cross_shadow(
    *,
    broker_code: str,
    uba_id: int,
    symbol: str,
    short_ma: Decimal,
    long_ma: Decimal,
    prev_short: Decimal,
    prev_long: Decimal,
    event_time: datetime | None = None,
    entry_reference_price: Decimal | None = None,
    scope_key: str | None = None,
) -> dict[str, Any]:
    """Golden Cross transition 시 K0 기록 — executor/order 미호출."""

    if str(broker_code or "").upper() != "KIWOOM":
        return {"ok": False, "reason": "NOT_KIWOOM"}
    if int(uba_id or 0) <= 0:
        return {"ok": False, "reason": "NO_UBA"}

    try:
        from stock_platform.common.settings import get_settings

        if not bool(
            getattr(get_settings(), "kiwoom_entry_signal_shadow_enabled", True)
        ):
            return {"ok": False, "reason": "DISABLED"}

        # episode dedupe — transition only (호출측에서 보장)
        if not (prev_short <= prev_long and short_ma > long_ma):
            return {"ok": False, "reason": "NOT_GOLDEN_CROSS_TRANSITION"}

        from stock_platform.database.session import get_session_factory
        from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.service import (
            enroll_golden_cross_observation,
        )

        observed_at = event_time or datetime.now(timezone.utc)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)

        sf = get_session_factory()
        session = sf()
        try:
            return enroll_golden_cross_observation(
                session,
                uba_id=int(uba_id),
                symbol=str(symbol).upper(),
                short_ma=short_ma,
                long_ma=long_ma,
                prev_short=prev_short,
                prev_long=prev_long,
                observed_at=observed_at,
                entry_reference_price=entry_reference_price,
                scope_key=scope_key,
                commit=True,
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.warning(
                "kiwoom_entry_signal_shadow_enroll_failed",
                extra={"error": type(exc).__name__, "uba": uba_id},
            )
            return {"ok": False, "error": type(exc).__name__}
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "kiwoom_entry_signal_shadow_hook_failed",
            extra={"error": type(exc).__name__},
        )
        return {"ok": False, "error": type(exc).__name__}
