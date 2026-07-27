from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.strategy_deployment.runtime_manager import (
    dynamic_strategy_runtime_manager,
)

logger = structlog.get_logger(__name__)


class StrategyRuntimeReloadScheduler:
    """등록된 Scope Runtime만 재로드 — 전역/기본 KRX 조회 없음."""

    def __init__(self) -> None:
        from stock_platform.common.settings import get_settings

        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )
        self._empty_logged = False

    @property
    def scheduler(self):
        return self._scheduler

    async def reload_active_strategy(self) -> None:
        status = dynamic_strategy_runtime_manager.status()
        count = int(status.get("scoped_runtime_count") or 0)
        if count == 0:
            if not self._empty_logged:
                logger.info(
                    "strategy_runtime_reload_skipped",
                    reason="No scoped runtimes registered",
                )
                self._empty_logged = True
            return

        self._empty_logged = False
        try:
            result = await dynamic_strategy_runtime_manager.reload_all_scopes(
                force=False
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "strategy_runtime_reload_batch_failed",
                error=str(exc),
            )
            return

        if int(result.get("changed") or 0) > 0:
            logger.info(
                "strategy_runtime_reloaded",
                changed=result.get("changed"),
                failed=len(result.get("failed") or []),
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


strategy_runtime_reload_scheduler = StrategyRuntimeReloadScheduler()
