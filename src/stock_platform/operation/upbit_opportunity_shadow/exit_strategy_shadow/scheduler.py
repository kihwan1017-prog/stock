"""Exit strategy shadow scheduler — attach to parent AsyncIOScheduler."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import distinct, select

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.constants import (
    STATUS_ACTIVE,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.entities import (
    UpbitExitStrategyShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.service import (
    observe_price_for_entry,
    shadow_enabled,
)
from stock_platform.position.exit_monitor_live import resolve_upbit_live_price

logger = structlog.get_logger(__name__)

JOB_ID = "upbit_exit_strategy_shadow_tracker"

_last_run_at: datetime | None = None
_last_success_at: datetime | None = None
_last_error: str | None = None


def scheduler_status() -> dict[str, Any]:
    return {
        "job_id": JOB_ID,
        "enabled": shadow_enabled(),
        "last_run_at": _last_run_at.isoformat() if _last_run_at else None,
        "last_success_at": (
            _last_success_at.isoformat() if _last_success_at else None
        ),
        "last_error": _last_error,
    }


def run_exit_strategy_shadow_tick(settings: Any | None = None) -> dict[str, Any]:
    """ACTIVE entry별 quote observe — REAL SELL 0."""

    global _last_run_at, _last_success_at, _last_error
    settings = settings or get_settings()
    _last_run_at = datetime.now(timezone.utc)
    if not shadow_enabled(settings):
        return {"ok": False, "reason": "DISABLED"}
    factory = get_session_factory()
    observed = 0
    triggered = 0
    try:
        with factory() as session:
            entry_ids = list(
                session.scalars(
                    select(
                        distinct(UpbitExitStrategyShadowEntity.entry_order_id)
                    ).where(
                        UpbitExitStrategyShadowEntity.status == STATUS_ACTIVE
                    )
                )
            )
            for oid in entry_ids:
                row = session.scalar(
                    select(UpbitExitStrategyShadowEntity).where(
                        UpbitExitStrategyShadowEntity.entry_order_id == int(oid)
                    ).limit(1)
                )
                if row is None:
                    continue
                px = resolve_upbit_live_price(
                    session,
                    symbol=str(row.symbol),
                    stale_seconds=30.0,
                )
                if px is None or px <= Decimal("0"):
                    continue
                # MA optional — fail-open without MA
                short_ma = long_ma = None
                try:
                    from stock_platform.realtime.ma_evaluator import (
                        try_read_cached_ma_pair,
                    )

                    pair = try_read_cached_ma_pair(str(row.symbol))
                    if pair:
                        short_ma, long_ma = pair
                except Exception:  # noqa: BLE001
                    pass
                result = observe_price_for_entry(
                    session,
                    entry_order_id=int(oid),
                    price=px,
                    observed_at=datetime.now(timezone.utc),
                    short_ma=short_ma,
                    long_ma=long_ma,
                )
                observed += 1
                triggered += int(result.get("triggered") or 0)
            session.commit()
        _last_success_at = datetime.now(timezone.utc)
        _last_error = None
        return {
            "ok": True,
            "entries_observed": observed,
            "triggered": triggered,
        }
    except Exception as exc:  # noqa: BLE001
        _last_error = str(exc)[:200]
        logger.warning(
            "exit_strategy_shadow_tick_failed",
            error=_last_error,
        )
        return {"ok": False, "error": _last_error}


class UpbitExitStrategyShadowScheduler:
    JOB_ID = JOB_ID

    def configure(self, parent_scheduler: Any) -> None:
        if not shadow_enabled():
            return
        settings = get_settings()
        interval = float(
            getattr(
                settings,
                "upbit_exit_strategy_shadow_interval_seconds",
                60,
            )
            or 60
        )
        interval = max(30.0, min(300.0, interval))

        async def _job() -> None:
            try:
                run_exit_strategy_shadow_tick()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "exit_strategy_shadow_scheduler_error",
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
