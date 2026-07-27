"""STEP 8-5-7 — KRX Calendar Sync / Coverage APScheduler."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory


class KrxTradingCalendarScheduler:
    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )
        self._configured = False

    def configure(self) -> None:
        if self._configured:
            return
        settings = get_settings()
        if not settings.krx_calendar_sync_enabled:
            self._configured = True
            return

        async def _sync() -> None:
            await self._run_sync(trigger="SCHEDULER")

        async def _coverage() -> None:
            await self._run_coverage()

        # 매일 01:10 KST 동기화
        self._scheduler.add_job(
            _sync,
            CronTrigger(
                hour=1,
                minute=10,
                timezone=settings.scheduler_timezone,
            ),
            id="krx_trading_calendar_sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        # 6시간마다 Coverage
        self._scheduler.add_job(
            _coverage,
            IntervalTrigger(hours=6),
            id="krx_trading_calendar_coverage_check",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._configured = True

    async def _run_sync(self, *, trigger: str) -> None:
        from stock_platform.broker.recovery_distributed_lock import (
            LockAcquireResult,
            LockReleaseReason,
            build_distributed_lock_manager_from_settings,
        )
        from stock_platform.broker.recovery_distributed_lock_scope import (
            RecoveryAccountKind,
            RecoveryLockScope,
        )
        from stock_platform.operation.calendar_sync_service import (
            TradingCalendarSyncService,
        )

        lock_mgr = build_distributed_lock_manager_from_settings()
        scope = RecoveryLockScope(
            account_kind=RecoveryAccountKind.SYSTEM,
            account_id=0,
            broker_code="KRX_CALENDAR",
            market_type="SYNC",
        )
        result, handle = lock_mgr.acquire(scope, timeout=0)
        if result in {
            LockAcquireResult.BUSY,
            LockAcquireResult.TIMEOUT,
        } or handle is None:
            logger.info(
                "krx_calendar_sync_skipped_busy",
                trigger=trigger,
            )
            return
        session = get_session_factory()()
        try:
            out = TradingCalendarSyncService(session).sync_krx(
                trigger_type=trigger,
                requested_by=f"apscheduler:{trigger}",
                mark_verified=True,
            )
            logger.info(
                "krx_calendar_sync_finished",
                status=out.get("status"),
                upserted=out.get("upserted_count"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "krx_calendar_sync_failed",
                error_type=exc.__class__.__name__,
                message=str(exc)[:500],
            )
        finally:
            session.close()
            try:
                lock_mgr.release(handle, LockReleaseReason.SUCCESS)
            except Exception:  # noqa: BLE001
                pass

    async def _run_coverage(self) -> None:
        from stock_platform.operation.calendar_sync_service import (
            TradingCalendarSyncService,
        )

        session = get_session_factory()()
        try:
            report = TradingCalendarSyncService(session).check_coverage()
            live_ok = report.get("coverage", {}).get(
                "live_trading_allowed"
            )
            logger.info(
                "krx_calendar_coverage_check",
                live_trading_allowed=live_ok,
                missing=report.get("coverage", {}).get("missing_days"),
            )
        finally:
            session.close()

    def start(self) -> None:
        self.configure()
        if not self._scheduler.running:
            self._scheduler.start()

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)


krx_trading_calendar_scheduler = KrxTradingCalendarScheduler()
