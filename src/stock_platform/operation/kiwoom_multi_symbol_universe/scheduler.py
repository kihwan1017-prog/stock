"""5분 주기 SHADOW refresh scheduler — REAL executor 미연결."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory


class KiwoomMultiSymbolUniverseScheduler:
    JOB_ID = "kiwoom_multi_symbol_universe_shadow"

    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)
        self._configured = False
        self._started = False
        self._refresh_count = 0
        self._last_result: dict[str, Any] | None = None
        self._last_run_at: datetime | None = None

    @staticmethod
    def enabled(settings: Any | None = None) -> bool:
        cfg = settings or get_settings()
        return bool(getattr(cfg, "kiwoom_multi_symbol_shadow_enabled", False))

    def configure(self, *, force: bool = False) -> None:
        if self._configured and not force:
            return
        settings = get_settings()
        if not self.enabled(settings):
            self._configured = True
            return
        interval = float(
            getattr(settings, "kiwoom_multi_symbol_refresh_interval_seconds", 300)
            or 300
        )
        interval = max(60.0, min(900.0, interval))
        if self._scheduler.get_job(self.JOB_ID):
            self._scheduler.remove_job(self.JOB_ID)
        self._scheduler.add_job(
            self._tick,
            trigger=IntervalTrigger(seconds=interval),
            id=self.JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._configured = True
        logger.info(
            "kiwoom_multi_symbol_scheduler_configured",
            interval_seconds=interval,
        )

    def start(self) -> dict[str, Any]:
        self.configure()
        if not self.enabled():
            return {"started": False, "reason": "DISABLED"}
        if not self._started:
            self._scheduler.start()
            self._started = True
        return {"started": True, "job_id": self.JOB_ID}

    def stop(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False

    def status(self) -> dict[str, Any]:
        return {
            "configured": self._configured,
            "started": self._started,
            "refresh_count": self._refresh_count,
            "last_run_at": self._last_run_at.isoformat() if self._last_run_at else None,
            "last_result": self._last_result,
        }

    async def _tick(self) -> None:
        settings = get_settings()
        if not self.enabled(settings):
            return
        uba_ids = self._active_kiwoom_uba_ids()
        if not uba_ids:
            default_uba = int(
                getattr(settings, "kiwoom_multi_symbol_default_uba_id", 1381) or 1381
            )
            uba_ids = [default_uba]

        from stock_platform.operation.kiwoom_multi_symbol_universe.service import (
            KiwoomMultiSymbolUniverseService,
        )

        sf = get_session_factory()
        results: list[dict[str, Any]] = []
        for uba_id in uba_ids:
            session = sf()
            try:
                svc = KiwoomMultiSymbolUniverseService(session)
                out = await svc.refresh(user_broker_account_id=uba_id)
                results.append(out)
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                logger.warning(
                    "kiwoom_multi_symbol_refresh_failed",
                    uba_id=uba_id,
                    error=type(exc).__name__,
                )
                results.append({"ok": False, "uba_id": uba_id, "error": type(exc).__name__})
            finally:
                session.close()

        self._refresh_count += 1
        self._last_run_at = datetime.now(timezone.utc)
        self._last_result = {"results": results, "count": len(results)}

    @staticmethod
    def _active_kiwoom_uba_ids() -> list[int]:
        from sqlalchemy import select

        from stock_platform.trading.live_unattended_entities import (
            LiveUnattendedAuthorizationEntity,
        )
        from stock_platform.trading.account_models import UserBrokerAccount

        sf = get_session_factory()
        session = sf()
        try:
            rows = session.scalars(
                select(LiveUnattendedAuthorizationEntity.user_broker_account_id)
                .join(
                    UserBrokerAccount,
                    UserBrokerAccount.user_broker_account_id
                    == LiveUnattendedAuthorizationEntity.user_broker_account_id,
                )
                .where(
                    LiveUnattendedAuthorizationEntity.enabled.is_(True),
                    LiveUnattendedAuthorizationEntity.status_code == "ACTIVE",
                    UserBrokerAccount.broker_code == "KIWOOM",
                )
            )
            return sorted({int(x) for x in rows if x})
        finally:
            session.close()


kiwoom_multi_symbol_universe_scheduler = KiwoomMultiSymbolUniverseScheduler()
