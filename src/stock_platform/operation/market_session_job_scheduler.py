"""STEP 8-5-15 — Market Session Job Dispatcher/Reconcile Scheduler (APScheduler).

`upbit_ambiguous_resolution_scheduler`와 동일한 원칙: DB Claim 기반이라
다중 인스턴스에서도 Leader Lock 없이 항상 기동 가능하다.
"""

from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory

logger = structlog.get_logger(__name__)

DISPATCH_JOB_ID = "market_session_job_dispatcher"
RECONCILE_JOB_ID = "market_session_job_reconcile"


class MarketSessionJobScheduler:
    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    async def _run_dispatch(self) -> None:
        from stock_platform.operation.market_session_job_dispatcher import (
            market_session_job_dispatcher,
        )

        try:
            result = await market_session_job_dispatcher.run_once()
            if result.get("status") not in {"NO_DUE", "DISABLED"}:
                logger.info(
                    "market_session_job_dispatch_finished",
                    status=result.get("status"),
                    processed=result.get("processed"),
                )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "market_session_job_dispatch_failed",
                error_type=exc.__class__.__name__,
                message=str(exc)[:400],
            )

    async def _run_reconcile(self) -> None:
        settings = get_settings()
        if not bool(settings.market_session_job_reconcile_enabled):
            return

        from stock_platform.operation.market_session_job_reconcile import (
            MarketSessionJobReconciliationService,
        )

        session = get_session_factory()()
        try:
            svc = MarketSessionJobReconciliationService(session)
            result = svc.reconcile()
            purge = svc.maybe_purge()
            logger.info(
                "market_session_job_reconcile_finished",
                checked_days=result.get("checked_days"),
                created=result.get("created"),
                expired_claims=result.get("expired_claims"),
                purge=purge,
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.error(
                "market_session_job_reconcile_failed",
                error_type=exc.__class__.__name__,
                message=str(exc)[:400],
            )
        finally:
            session.close()

    def configure(self) -> None:
        settings = get_settings()
        poll = max(
            1, int(settings.market_session_job_dispatcher_poll_seconds)
        )
        self._scheduler.add_job(
            self._run_dispatch,
            trigger=IntervalTrigger(seconds=poll),
            id=DISPATCH_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(poll, 5),
        )
        if bool(settings.market_session_job_reconcile_enabled):
            interval = max(
                30,
                int(settings.market_session_job_reconcile_interval_seconds),
            )
            self._scheduler.add_job(
                self._run_reconcile,
                trigger=IntervalTrigger(seconds=interval),
                id=RECONCILE_JOB_ID,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=max(interval, 30),
            )

    def start(self) -> None:
        settings = get_settings()
        if not bool(settings.market_session_job_enabled):
            logger.info(
                "market_session_job_scheduler_skipped",
                reason="disabled_by_settings",
            )
            return
        if self._scheduler.running:
            return
        self.configure()
        self._scheduler.start()
        logger.info(
            "market_session_job_scheduler_started",
            poll_seconds=settings.market_session_job_dispatcher_poll_seconds,
        )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("market_session_job_scheduler_stopped")

    def status(self) -> dict:
        dispatch_job = self._scheduler.get_job(DISPATCH_JOB_ID)
        reconcile_job = self._scheduler.get_job(RECONCILE_JOB_ID)
        return {
            "running": bool(self._scheduler.running),
            "dispatch_job_registered": dispatch_job is not None,
            "reconcile_job_registered": reconcile_job is not None,
            "dispatch_next_run_at": (
                dispatch_job.next_run_time.isoformat()
                if dispatch_job is not None
                and dispatch_job.next_run_time is not None
                else None
            ),
            "reconcile_next_run_at": (
                reconcile_job.next_run_time.isoformat()
                if reconcile_job is not None
                and reconcile_job.next_run_time is not None
                else None
            ),
        }


market_session_job_scheduler = MarketSessionJobScheduler()
