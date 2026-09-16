"""Scheduler tick — research only, fail-open."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.orm import Session

from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.service import (
    scan_and_enroll_open_exits,
    shadow_enabled,
    tick_active_observations,
)

logger = structlog.get_logger(__name__)
JOB_ID = "upbit_exit_order_recovery_shadow_tick"


def run_exit_order_recovery_shadow_tick(settings: Any | None = None) -> dict[str, Any]:
    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED", "REAL_TRADING_BLOCKED": False}
    sf = get_session_factory()
    try:
        with sf() as session:  # type: Session
            enrolled = scan_and_enroll_open_exits(session)
            tick = tick_active_observations(session)
            session.commit()
            return {
                "ok": True,
                "enroll": enrolled,
                "tick": tick,
                "REAL_TRADING_BLOCKED": False,
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "exit_order_recovery_shadow_scheduler_failed",
            error=str(exc)[:200],
        )
        return {
            "ok": False,
            "error": str(exc)[:200],
            "REAL_TRADING_BLOCKED": False,
        }


def configure_exit_order_recovery_shadow_scheduler(
    scheduler: Any,
    settings: Any,
) -> None:
    if not shadow_enabled(settings):
        return
    interval = float(
        getattr(settings, "upbit_exit_order_recovery_shadow_interval_seconds", 60.0)
        or 60.0
    )
    try:
        scheduler.add_job(
            run_exit_order_recovery_shadow_tick,
            "interval",
            seconds=max(15.0, interval),
            id=JOB_ID,
            replace_existing=True,
            kwargs={"settings": settings},
            coalesce=True,
            max_instances=1,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "exit_order_recovery_shadow_scheduler_configure_failed",
            error=str(exc)[:200],
        )
