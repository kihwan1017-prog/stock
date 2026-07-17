from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.strategy_deployment.automation_service import (
    StrategyAutoDeploymentService,
)


class StrategyApprovalScheduler:
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
                minute=10,
            ),
            id="strategy_approval_after_market",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=600,
        )

    async def run_after_market(self) -> None:
        settings = get_settings()

        session = get_session_factory()()

        try:
            StrategyAutoDeploymentService(
                session=session
            ).evaluate_latest(
                market_code=settings.realtime_strategy_market_code,
                symbol=settings.realtime_strategy_symbol_or_none,
                requested_by="SYSTEM_SCHEDULER",
                auto_deploy=settings.strategy_auto_deploy_enabled,
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def start(self) -> None:
        if self._scheduler.running:
            return
        self.configure()
        self._scheduler.start()

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)


strategy_approval_scheduler = (
    StrategyApprovalScheduler()
)
