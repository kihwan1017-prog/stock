"""자동매매 일일 운영보고 Telegram 스케줄 — 23:30 KST, fail-open."""

from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.autotrading_daily_report_service import (
    build_autotrading_daily_report,
    format_daily_report_telegram,
    telegram_dedupe_key,
    was_daily_report_sent,
)

logger = structlog.get_logger(__name__)
_KST = ZoneInfo("Asia/Seoul")


class AutotradingDailyReportScheduler:
    """Report 전용 — autotrading decision path와 분리."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone=_KST)
        self._started = False

    def start(self) -> dict[str, object]:
        settings = get_settings()
        if not bool(getattr(settings, "autotrading_daily_report_telegram_enabled", True)):
            return {"started": False, "reason": "DISABLED_BY_SETTINGS"}
        if self._started:
            return {"started": True, "reason": "ALREADY_STARTED", "idempotent": True}

        hour = int(getattr(settings, "autotrading_daily_report_hour_kst", 23))
        minute = int(getattr(settings, "autotrading_daily_report_minute_kst", 30))
        self._scheduler.add_job(
            self._run_daily_telegram,
            CronTrigger(hour=hour, minute=minute, timezone=_KST),
            id="autotrading_daily_report_telegram",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        self._started = True
        return {
            "started": True,
            "schedule_kst": f"{hour:02d}:{minute:02d}",
            "idempotency_prefix": "DAILY_TRADING_REPORT:",
        }

    def stop(self) -> dict[str, object]:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
        return {"stopped": True}

    def status(self) -> dict[str, object]:
        jobs = []
        if self._started:
            for job in self._scheduler.get_jobs():
                jobs.append({"id": job.id, "next_run": str(job.next_run_time)})
        return {"started": self._started, "jobs": jobs}

    async def _run_daily_telegram(self) -> None:
        """실패해도 trading fail-open — 로그만."""

        from datetime import datetime

        report_date = datetime.now(_KST).date()
        sf = get_session_factory()
        session = sf()
        try:
            if was_daily_report_sent(session, report_date):
                logger.info(
                    "autotrading_daily_report_telegram_skipped",
                    reason="ALREADY_SENT",
                    report_date=report_date.isoformat(),
                )
                return

            report = build_autotrading_daily_report(
                session, report_date=report_date, market="ALL"
            )
            body = format_daily_report_telegram(report)
            dedupe = telegram_dedupe_key(report_date)

            from stock_platform.notification.inbox_models import Notification
            from stock_platform.notification.inbox_repository import (
                NotificationInboxRepository,
            )

            repo = NotificationInboxRepository(session)
            if repo.find_by_dedupe(dedupe) is None:
                repo.add_notification(
                    Notification(
                        event_type="AUTOTRADING_DAILY_REPORT",
                        title="[시스템] 자동매매 일일보고",
                        message=body,
                        payload_json={"report_date": report_date.isoformat()},
                        severity="INFO",
                        dedupe_key=dedupe,
                    )
                )
                session.flush()

            from stock_platform.order.live_safety_audit import emit_live_order_telegram

            emit_live_order_telegram(
                event_type="AUTOTRADING_DAILY_REPORT",
                title="[시스템] 자동매매 일일보고",
                message=body,
                detail={"report_date": report_date.isoformat(), "dedupe_key": dedupe},
            )
            session.commit()

            logger.info(
                "autotrading_daily_report_telegram_sent",
                report_date=report_date.isoformat(),
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.exception(
                "autotrading_daily_report_telegram_failed",
                error=str(exc)[:300],
            )
        finally:
            session.close()


autotrading_daily_report_scheduler = AutotradingDailyReportScheduler()
