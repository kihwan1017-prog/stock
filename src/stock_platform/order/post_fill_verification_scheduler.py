"""STEP 8-8A — Post-Fill Verification Scheduler (APScheduler)."""

from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory

logger = structlog.get_logger(__name__)

JOB_ID = "post_fill_verification_dispatcher"


class PostFillVerificationScheduler:
    """DB Claim 기반 — Multi-Worker에서도 Leader Lock 없이 기동."""

    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    async def _run_job(self) -> None:
        from stock_platform.order.post_fill_verification_service import (
            PostFillVerificationService,
        )

        session = get_session_factory()()
        try:
            result = await PostFillVerificationService(
                session
            ).run_once_async()
            if result.get("status") not in {"NO_DUE", "DISABLED"}:
                logger.info(
                    "post_fill_verification_run_finished",
                    status=result.get("status"),
                    processed=result.get("processed"),
                )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.error(
                "post_fill_verification_run_failed",
                error_type=exc.__class__.__name__,
                message=str(exc)[:400],
            )
        finally:
            session.close()

    def configure(self) -> None:
        settings = get_settings()
        if not bool(getattr(settings, "post_fill_verify_enabled", True)):
            return
        interval = max(
            1, int(getattr(settings, "post_fill_verify_poll_seconds", 2))
        )
        self._scheduler.add_job(
            self._run_job,
            trigger=IntervalTrigger(seconds=interval),
            id=JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def start(self) -> None:
        settings = get_settings()
        if not bool(getattr(settings, "post_fill_verify_enabled", True)):
            logger.info("post_fill_verification_scheduler_disabled")
            return
        if not self._scheduler.running:
            self.configure()
            self._scheduler.start()
            logger.info("post_fill_verification_scheduler_started")

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("post_fill_verification_scheduler_stopped")


post_fill_verification_scheduler = PostFillVerificationScheduler()
