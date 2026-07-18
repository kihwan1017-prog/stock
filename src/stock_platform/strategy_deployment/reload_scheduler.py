from __future__ import annotations

import structlog
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

logger = structlog.get_logger(__name__)


class StrategyRuntimeReloadScheduler:
    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )
        self._missing_logged = False

    @property
    def scheduler(self):
        return self._scheduler

    async def reload_active_strategy(self) -> None:
        settings = get_settings()

        try:
            result = await dynamic_strategy_runtime_manager.reload(
                market_code=settings.realtime_strategy_market_code,
                symbol=settings.realtime_strategy_symbol_or_none,
                force=False,
            )
        except LookupError as exc:
            # 활성 배포가 없으면 Day-1/로컬에서 정상. traceback 대신 1회만 안내.
            if not self._missing_logged:
                logger.info(
                    "strategy_runtime_reload_skipped",
                    reason=str(exc),
                )
                self._missing_logged = True
            return

        self._missing_logged = False
        if result.changed:
            logger.info(
                "strategy_runtime_reloaded",
                deployment_id=result.current_deployment_id,
                strategy_code=result.strategy_code,
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
