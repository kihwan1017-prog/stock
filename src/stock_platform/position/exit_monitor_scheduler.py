"""Position Exit Monitor 폴링 스케줄러."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import (
    AsyncIOScheduler,
)
from apscheduler.triggers.interval import (
    IntervalTrigger,
)

import structlog

from stock_platform.common.settings import get_settings
from stock_platform.position.exit_monitor_runtime import (
    position_exit_monitor_manager,
)


logger = structlog.get_logger(__name__)


class PositionExitMonitorScheduler:
    """Polling 방식 — 설정 주기마다 오픈 포지션을 검사한다."""

    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )

    @property
    def scheduler(self):
        return self._scheduler

    def configure(self) -> None:
        settings = get_settings()
        interval = max(
            1.0,
            float(
                settings.position_exit_monitor_interval_seconds
            ),
        )
        self._scheduler.add_job(
            position_exit_monitor_manager.check_now,
            trigger=IntervalTrigger(seconds=interval),
            id="position_exit_monitor",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(int(interval), 5),
        )

    def start(self) -> None:
        settings = get_settings()
        if not settings.position_exit_monitor_enabled:
            logger.info(
                "position_exit_monitor_skipped",
                reason="disabled_by_settings",
            )
            return

        if self._scheduler.running:
            return

        self.configure()
        self._scheduler.start()
        logger.info(
            "position_exit_monitor_started",
            interval_seconds=(
                settings.position_exit_monitor_interval_seconds
            ),
        )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("position_exit_monitor_stopped")


position_exit_monitor_scheduler = (
    PositionExitMonitorScheduler()
)
