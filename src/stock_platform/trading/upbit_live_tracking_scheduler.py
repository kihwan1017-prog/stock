"""STEP 8-9A — Upbit Live Smoke Broker Tracking + open-order fill poller."""

from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.trading.live_validation_entities import (
    LiveValidationRunEntity,
)
from stock_platform.trading.upbit_live_tracking_service import (
    UpbitLiveTrackingService,
)

logger = structlog.get_logger(__name__)

JOB_ID = "upbit_live_smoke_broker_tracker"
JOB_ID_OPEN_FILL = "upbit_open_order_fill_poller"


class UpbitLiveTrackingScheduler:
    """거래 Scheduler와 분리 — 미확정 Broker 주문만 추적."""

    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    def status(self) -> dict[str, object]:
        running = bool(self._scheduler.running)
        job = None
        fill_job = None
        if running:
            job = self._scheduler.get_job(JOB_ID)
            fill_job = self._scheduler.get_job(JOB_ID_OPEN_FILL)
        return {
            "enabled": bool(
                getattr(get_settings(), "upbit_live_track_enabled", True)
            ),
            "running": running,
            "job_id": JOB_ID,
            "open_fill_job_id": JOB_ID_OPEN_FILL,
            "next_run_at": (
                job.next_run_time.isoformat()
                if job is not None and job.next_run_time
                else None
            ),
            "open_fill_next_run_at": (
                fill_job.next_run_time.isoformat()
                if fill_job is not None and fill_job.next_run_time
                else None
            ),
        }

    async def _run_job(self) -> None:
        session = get_session_factory()()
        try:
            svc = UpbitLiveTrackingService(session)
            ids = svc.select_due_run_ids(limit=20)
            processed = 0
            for pk in ids:
                row = session.get(LiveValidationRunEntity, pk)
                if row is None:
                    continue
                svc.track_once(row, actor="UPBIT_LIVE_TRACKER")
                processed += 1
            if processed:
                session.commit()
                logger.info(
                    "upbit_live_track_run_finished",
                    processed=processed,
                )
            else:
                session.rollback()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.error(
                "upbit_live_track_run_failed",
                error_type=exc.__class__.__name__,
                message=str(exc)[:400],
            )
        finally:
            session.close()

    async def _run_open_order_fill_poll(self) -> None:
        """ACCEPTED 등 local open → broker GET → fill sync (재주문 없음)."""

        session = get_session_factory()()
        try:
            from stock_platform.broker.upbit.open_order_fill_poller import (
                UpbitOpenOrderFillPoller,
            )

            result = UpbitOpenOrderFillPoller(session).poll_once(
                limit=40,
                actor="UPBIT_OPEN_ORDER_FILL_POLLER",
            )
            if int(result.get("updated") or 0) > 0 or int(
                result.get("checked") or 0
            ) > 0:
                session.commit()
                if int(result.get("updated") or 0) > 0:
                    logger.info(
                        "upbit_open_order_fill_poll_finished",
                        checked=result.get("checked"),
                        updated=result.get("updated"),
                        errors=result.get("errors"),
                    )
            else:
                session.rollback()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.error(
                "upbit_open_order_fill_poll_failed",
                error_type=exc.__class__.__name__,
                message=str(exc)[:400],
            )
        finally:
            session.close()

    def configure(self) -> None:
        settings = get_settings()
        if not bool(getattr(settings, "upbit_live_track_enabled", True)):
            return
        interval = max(
            1, int(getattr(settings, "upbit_live_track_poll_seconds", 2))
        )
        self._scheduler.add_job(
            self._run_job,
            trigger=IntervalTrigger(seconds=interval),
            id=JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        # open-order fill sync — smoke tracker와 동일 interval
        self._scheduler.add_job(
            self._run_open_order_fill_poll,
            trigger=IntervalTrigger(seconds=interval),
            id=JOB_ID_OPEN_FILL,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def start(self) -> None:
        settings = get_settings()
        if not bool(getattr(settings, "upbit_live_track_enabled", True)):
            logger.info("upbit_live_track_scheduler_disabled")
            return
        if not self._scheduler.running:
            self.configure()
            self._scheduler.start()
            logger.info("upbit_live_track_scheduler_started")

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("upbit_live_track_scheduler_stopped")


upbit_live_tracking_scheduler = UpbitLiveTrackingScheduler()
