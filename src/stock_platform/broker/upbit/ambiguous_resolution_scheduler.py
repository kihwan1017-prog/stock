"""STEP 8-5-14 — Upbit Ambiguous Order Resolver Scheduler (APScheduler)."""

from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory

logger = structlog.get_logger(__name__)

JOB_ID = "upbit_ambiguous_order_resolver"


class UpbitAmbiguousOrderResolutionScheduler:
    """DB Claim 기반이므로 Multi-Worker에서도 항상 기동 가능 (Outbox와 동일 원칙).

    Lifecycle Leader Lock 여부와 무관하게 시작한다 — DB Claim이 중복 처리를
    막아주기 때문에 Leader 전용 Scheduler일 필요가 없다.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    async def _run_job(self) -> None:
        from stock_platform.broker.upbit.ambiguous_resolution_service import (
            UpbitAmbiguousOrderResolutionService,
        )

        session = get_session_factory()()
        try:
            result = UpbitAmbiguousOrderResolutionService(
                session
            ).run_once(trigger_type="SCHEDULER")
            if result.get("status") not in {"NO_DUE", "DISABLED"}:
                logger.info(
                    "upbit_ambiguous_resolver_run_finished",
                    **{
                        k: v
                        for k, v in result.items()
                        if k
                        in {
                            "status",
                            "run_id",
                            "due_count",
                            "claimed_count",
                            "found_count",
                            "error_count",
                        }
                    },
                )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.error(
                "upbit_ambiguous_resolver_run_failed",
                error_type=exc.__class__.__name__,
                message=str(exc)[:400],
            )
        finally:
            session.close()

    def configure(self) -> None:
        settings = get_settings()
        interval = max(
            1, int(settings.upbit_ambiguous_resolver_poll_seconds)
        )
        self._scheduler.add_job(
            self._run_job,
            trigger=IntervalTrigger(seconds=interval),
            id=JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(interval, 5),
        )

    def start(self) -> None:
        settings = get_settings()
        if not settings.upbit_ambiguous_resolver_enabled:
            logger.info(
                "upbit_ambiguous_resolver_scheduler_skipped",
                reason="disabled_by_settings",
            )
            return
        if self._scheduler.running:
            return
        self.configure()
        self._scheduler.start()
        logger.info(
            "upbit_ambiguous_resolver_scheduler_started",
            poll_seconds=settings.upbit_ambiguous_resolver_poll_seconds,
        )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("upbit_ambiguous_resolver_scheduler_stopped")

    def status(self) -> dict:
        job = self._scheduler.get_job(JOB_ID)
        next_run = getattr(job, "next_run_time", None) if job else None
        return {
            "running": bool(self._scheduler.running),
            "job_registered": job is not None,
            "next_run_at": (
                next_run.isoformat() if next_run is not None else None
            ),
        }


upbit_ambiguous_order_resolution_scheduler = (
    UpbitAmbiguousOrderResolutionScheduler()
)
