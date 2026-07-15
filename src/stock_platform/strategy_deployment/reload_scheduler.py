from __future__ import annotations

import os

from apscheduler.schedulers.asyncio import (
    AsyncIOScheduler,
)
from apscheduler.triggers.interval import (
    IntervalTrigger,
)

from stock_platform.common.settings import (
    get_settings,
)
from stock_platform.strategy_deployment.runtime_manager import (
    dynamic_strategy_runtime_manager,
)


class StrategyRuntimeReloadScheduler:
    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )

    @property
    def scheduler(self):
        return self._scheduler

    async def reload_active_strategy(self) -> None:
        market_code = os.getenv(
            "REALTIME_STRATEGY_MARKET_CODE",
            "KRX",
        ).strip()
        symbol = os.getenv(
            "REALTIME_STRATEGY_SYMBOL",
            "",
        ).strip() or None

        await dynamic_strategy_runtime_manager.reload(
            market_code=market_code,
            symbol=symbol,
            force=False,
        )

    def configure(self) -> None:
        self._scheduler.add_job(
            self.reload_active_strategy,
            trigger=IntervalTrigger(seconds=30),
            id="strategy_runtime_reload",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=30,
        )

    def start(self) -> None:
        if self._scheduler.running:
            return

        self.configure()
        self._scheduler.start()

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)


strategy_runtime_reload_scheduler = (
    StrategyRuntimeReloadScheduler()
)
