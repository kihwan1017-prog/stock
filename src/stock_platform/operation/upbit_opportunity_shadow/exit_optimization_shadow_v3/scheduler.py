"""V3 shadow scheduler — continuation ticks after REAL close."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.constants import (
    STATUS_ACTIVE,
    STATUS_CONTINUATION,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.entities import (
    UpbitExitOptimizationShadowV3EnrollmentEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.service import (
    observe_price_tick,
    shadow_enabled,
)
from stock_platform.position.exit_monitor_live import resolve_upbit_live_price

logger = structlog.get_logger(__name__)

JOB_ID = "upbit_exit_optimization_shadow_v3_tracker"


def run_exit_optimization_v3_tick(settings: Any | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}

    factory = get_session_factory()
    observed = 0
    with factory() as session:
        rows = list(
            session.scalars(
                select(UpbitExitOptimizationShadowV3EnrollmentEntity).where(
                    UpbitExitOptimizationShadowV3EnrollmentEntity.status.in_(
                        (STATUS_ACTIVE, STATUS_CONTINUATION)
                    )
                )
            )
        )
        for row in rows:
            px = resolve_upbit_live_price(
                session,
                symbol=str(row.symbol),
                stale_seconds=30.0,
            )
            if px is None or px <= Decimal("0"):
                continue
            observe_price_tick(
                session,
                binding_id=int(row.binding_id),
                price=px,
                observed_at=datetime.now(timezone.utc),
            )
            observed += 1
        session.commit()
    return {"ok": True, "observed": observed}


class UpbitExitOptimizationShadowV3Scheduler:
    JOB_ID = JOB_ID

    def configure(self, parent_scheduler: Any) -> None:
        if not shadow_enabled():
            return
        settings = get_settings()
        interval = float(
            getattr(
                settings,
                "upbit_exit_optimization_shadow_v3_interval_seconds",
                60,
            )
            or 60
        )
        interval = max(30.0, min(300.0, interval))

        async def _job() -> None:
            try:
                run_exit_optimization_v3_tick()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "exit_optimization_shadow_v3_scheduler_error",
                    error=str(exc)[:200],
                )

        parent_scheduler.add_job(
            _job,
            IntervalTrigger(seconds=interval),
            id=self.JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(int(interval), 60),
        )
