from __future__ import annotations

import os

from apscheduler.schedulers.asyncio import (
    AsyncIOScheduler,
)
from apscheduler.triggers.cron import CronTrigger

from stock_platform.common.settings import (
    get_settings,
)
from stock_platform.strategy_deployment.pipeline_runtime import (
    strategy_deployment_pipeline_manager,
)


class StrategyDeploymentPipelineScheduler:
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
                minute=20,
            ),
            id="strategy_deployment_pipeline",
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

        await strategy_deployment_pipeline_manager.run(
            market_code=market_code,
            symbol=symbol,
            requested_by="SYSTEM_PIPELINE",
            sample_context={},
            allow_auto_deploy=None,
        )

    def start(self) -> None:
        if self._scheduler.running:
            return

        self.configure()
        self._scheduler.start()

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)


strategy_deployment_pipeline_scheduler = (
    StrategyDeploymentPipelineScheduler()
)
