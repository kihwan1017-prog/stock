from __future__ import annotations

from apscheduler.schedulers.asyncio import (
    AsyncIOScheduler,
)
from apscheduler.triggers.interval import (
    IntervalTrigger,
)

from stock_platform.common.settings import (
    get_settings,
)
from stock_platform.risk_engine.daily_loss_runtime import (
    daily_loss_monitor_manager,
)


class DailyLossMonitorScheduler:
    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )

    @property
    def scheduler(self):
        return self._scheduler

    def configure(self) -> None:
        self._scheduler.add_job(
            daily_loss_monitor_manager.check_now,
            trigger=IntervalTrigger(minutes=1),
            id="daily_loss_monitor",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )

    def start(self) -> None:
        if self._scheduler.running:
            return
        self.configure()
        self._scheduler.start()

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)


daily_loss_monitor_scheduler = (
    DailyLossMonitorScheduler()
)
