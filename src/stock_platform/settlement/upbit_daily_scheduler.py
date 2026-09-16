"""STEP 8-5-16 — Upbit Daily Settlement Scheduler (KRX Calendar 비연동)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory

logger = structlog.get_logger(__name__)

JOB_ID = "upbit_daily_settlement"


class UpbitDailySettlementScheduler:
    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )

    def status(self) -> dict:
        return {
            "running": bool(self._scheduler.running),
            "job_id": JOB_ID,
            "enabled": bool(
                get_settings().upbit_daily_settlement_enabled
            ),
        }

    async def _run_job(self) -> None:
        from stock_platform.settlement.runner import (
            run_upbit_daily_settlement,
        )

        settings = get_settings()
        if not settings.upbit_daily_settlement_enabled:
            return
        if not settings.settlement_enabled:
            return
        tz = ZoneInfo("Asia/Seoul")
        market_date = datetime.now(tz).date()
        session = get_session_factory()()
        try:
            summary = run_upbit_daily_settlement(
                session, market_date=market_date
            )
            logger.info(
                "upbit_daily_settlement_finished",
                **(summary.get("counts") or {}),
            )
        except Exception:  # noqa: BLE001
            logger.exception("upbit_daily_settlement_failed")
            session.rollback()
        finally:
            session.close()

    def start(self) -> None:
        settings = get_settings()
        if not settings.upbit_daily_settlement_enabled:
            logger.info("upbit_daily_settlement_scheduler_skipped")
            return
        if self._scheduler.running:
            return
        self._scheduler.add_job(
            self._run_job,
            trigger=CronTrigger(
                hour=int(settings.upbit_daily_settlement_hour),
                minute=int(settings.upbit_daily_settlement_minute),
                timezone="Asia/Seoul",
            ),
            id=JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info(
            "upbit_daily_settlement_scheduler_started",
            hour=settings.upbit_daily_settlement_hour,
            minute=settings.upbit_daily_settlement_minute,
        )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)


upbit_daily_settlement_scheduler = UpbitDailySettlementScheduler()
