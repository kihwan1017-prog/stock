from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from stock_platform.common.settings import Settings, get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.scheduler.service import SchedulerService


logger = structlog.get_logger(__name__)


class AutomaticScheduler:
    """장후 자동 작업을 실행하는 APScheduler 래퍼."""

    def __init__(
        self,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=self._settings.scheduler_timezone
        )

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    def configure(self) -> None:
        self._scheduler.add_job(
            self._run_candidate_screening,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=self._settings.scheduler_candidate_hour,
                minute=self._settings.scheduler_candidate_minute,
                timezone=self._settings.scheduler_timezone,
            ),
            id="candidate_screening_daily",
            name="Candidate screening daily",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )

        self._scheduler.add_job(
            self._run_ai_orchestration,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=self._settings.scheduler_ai_hour,
                minute=self._settings.scheduler_ai_minute,
                timezone=self._settings.scheduler_timezone,
            ),
            id="ai_orchestration_daily",
            name="AI orchestration daily",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )

        self._scheduler.add_job(
            self._run_position_planning,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=self._settings.scheduler_position_hour,
                minute=self._settings.scheduler_position_minute,
                timezone=self._settings.scheduler_timezone,
            ),
            id="position_planning_daily",
            name="Position planning daily",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )

    def start(self) -> None:
        if not self._settings.scheduler_enabled:
            logger.info("automatic_scheduler_disabled")
            return

        self.configure()
        self._scheduler.start()

        logger.info(
            "automatic_scheduler_started",
            timezone=self._settings.scheduler_timezone,
            jobs=[
                job.id
                for job in self._scheduler.get_jobs()
            ],
        )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)

    async def run_job_now(
        self,
        job_name: str,
    ) -> dict[str, Any]:
        mapping = {
            "candidate_screening": (
                self._run_candidate_screening
            ),
            "ai_orchestration": (
                self._run_ai_orchestration
            ),
            "position_planning": (
                self._run_position_planning
            ),
        }

        try:
            handler = mapping[job_name]
        except KeyError as exc:
            raise LookupError(
                f"Automatic job not found: {job_name}"
            ) from exc

        return await handler()

    async def _execute_registered_job(
        self,
        *,
        job_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        session = get_session_factory()()

        try:
            history, result = await SchedulerService(
                session
            ).execute(
                job_name=job_name,
                payload=payload,
                trigger_type="SCHEDULED",
            )

            logger.info(
                "automatic_job_completed",
                job_name=job_name,
                job_run_id=history.job_run_id,
                status_code=history.status_code,
            )

            return {
                "job_run_id": history.job_run_id,
                "status_code": history.status_code,
                "result": result,
            }
        except Exception:
            logger.exception(
                "automatic_job_failed",
                job_name=job_name,
            )
            raise
        finally:
            session.close()

    async def _run_candidate_screening(
        self,
    ) -> dict[str, Any]:
        return await self._execute_registered_job(
            job_name="candidate_screening",
            payload={
                "exchange_code": (
                    self._settings.scheduler_exchange_code
                ),
                "as_of_date": date.today().isoformat(),
                "limit": (
                    self._settings.scheduler_candidate_limit
                ),
                "minimum_score": (
                    self._settings.scheduler_minimum_score
                ),
                "require_all_rules": False,
                "run_type": "DAILY",
            },
        )

    async def _run_ai_orchestration(
        self,
    ) -> dict[str, Any]:
        return await self._execute_registered_job(
            job_name="ai_orchestration",
            payload={
                "exchange_code": (
                    self._settings.scheduler_exchange_code
                ),
                "limit": self._settings.scheduler_ai_limit,
                "news_limit": 20,
                "disclosure_limit": 20,
                "lookback_days": 90,
            },
        )

    async def _run_position_planning(
        self,
    ) -> dict[str, Any]:
        return await self._execute_registered_job(
            job_name="position_planning",
            payload={
                "exchange_code": (
                    self._settings.scheduler_exchange_code
                ),
                "policy_id": (
                    self._settings.scheduler_policy_id
                ),
                "portfolio_value": (
                    self._settings.scheduler_portfolio_value
                ),
                "available_cash": (
                    self._settings.scheduler_available_cash
                ),
                "current_position_count": 0,
                "limit": (
                    self._settings.scheduler_position_limit
                ),
                "minimum_ai_score": (
                    self._settings.scheduler_minimum_ai_score
                ),
                "minimum_confidence": (
                    self._settings
                    .scheduler_minimum_confidence
                ),
                "allowed_actions": [
                    "WATCH",
                    "REVIEW",
                ],
            },
        )


async def run_forever() -> None:
    scheduler = AutomaticScheduler()
    scheduler.start()

    stop_event = asyncio.Event()

    try:
        await stop_event.wait()
    finally:
        await scheduler.shutdown()
