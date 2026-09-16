"""Waiting lifecycle shadow scheduler — attach to opportunity-shadow parent."""

from __future__ import annotations

from typing import Any

import structlog
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.service import (
    shadow_enabled,
    tick_active_observations,
)

logger = structlog.get_logger(__name__)

JOB_ID = "upbit_waiting_lifecycle_shadow_tick"


def run_waiting_lifecycle_shadow_tick(settings: Any | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}
    factory = get_session_factory()
    try:
        with factory() as session:
            out = tick_active_observations(session)
            session.commit()
            return out
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "waiting_lifecycle_shadow_tick_failed",
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}


class UpbitWaitingLifecycleShadowScheduler:
    JOB_ID = JOB_ID

    def configure(self, parent_scheduler: Any) -> None:
        if not shadow_enabled():
            return
        settings = get_settings()
        interval = float(
            getattr(
                settings,
                "upbit_waiting_lifecycle_shadow_interval_seconds",
                60.0,
            )
            or 60.0
        )
        parent_scheduler.add_job(
            run_waiting_lifecycle_shadow_tick,
            trigger=IntervalTrigger(seconds=max(15.0, interval)),
            id=JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
