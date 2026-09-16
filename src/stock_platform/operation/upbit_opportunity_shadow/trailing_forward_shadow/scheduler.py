"""Trailing forward shadow scheduler — attach to parent AsyncIOScheduler."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.constants import (
    STATUS_ACTIVE,
)
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.entities import (
    UpbitTrailingForwardShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.service import (
    observe_price_tick,
    shadow_enabled,
)
from stock_platform.position.exit_monitor_live import resolve_upbit_live_price

logger = structlog.get_logger(__name__)

JOB_ID = "upbit_trailing_forward_shadow_tracker"


def run_trailing_shadow_tick(settings: Any | None = None) -> dict[str, Any]:
    """ACTIVE trailing shadow rows — quote observe only (REAL SELL 0)."""

    settings = settings or get_settings()
    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}
    factory = get_session_factory()
    observed = 0
    with factory() as session:
        rows = list(
            session.scalars(
                select(UpbitTrailingForwardShadowEntity).where(
                    UpbitTrailingForwardShadowEntity.status == STATUS_ACTIVE
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
                quantity=row.entry_quantity,
            )
            observed += 1
        session.commit()
    return {"ok": True, "observed": observed}


class UpbitTrailingForwardShadowScheduler:
    """부모 opportunity-shadow scheduler에 job 부착."""

    JOB_ID = JOB_ID

    def configure(self, parent_scheduler: Any) -> None:
        if not shadow_enabled():
            return
        settings = get_settings()
        interval = float(
            getattr(
                settings,
                "upbit_trailing_forward_shadow_interval_seconds",
                60,
            )
            or 60
        )
        interval = max(30.0, min(300.0, interval))

        async def _job() -> None:
            try:
                run_trailing_shadow_tick()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "trailing_forward_shadow_scheduler_error",
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
