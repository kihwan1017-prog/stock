from __future__ import annotations

import os

from apscheduler.schedulers.asyncio import (
    AsyncIOScheduler,
)
from apscheduler.triggers.cron import CronTrigger

from stock_platform.common.settings import (
    get_settings,
)
from stock_platform.strategy_deployment.performance_monitor_runtime import (
    deployment_performance_monitor_manager,
)


class DeploymentPerformanceMonitorScheduler:
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
            self.run_after_market,
            trigger=CronTrigger(
                hour=16,
                minute=30,
            ),
            id="paper_strategy_performance_monitor",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=600,
        )

    async def run_after_market(self) -> None:
        market_code = os.getenv(
            "REALTIME_STRATEGY_MARKET_CODE",
            "KRX",
        ).strip()
        symbol = os.getenv(
            "REALTIME_STRATEGY_SYMBOL",
            "",
        ).strip() or None

        deployment_performance_monitor_manager.check_active(
            market_code=market_code,
            symbol=symbol,
        )

    def start(self) -> None:
        if self._scheduler.running:
            return
        self.configure()
        self._scheduler.start()

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)


deployment_performance_monitor_scheduler = (
    DeploymentPerformanceMonitorScheduler()
)
