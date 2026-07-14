from __future__ import annotations

from apscheduler.schedulers.asyncio import (
    AsyncIOScheduler,
)
from apscheduler.triggers.cron import CronTrigger

from stock_platform.common.settings import (
    Settings,
    get_settings,
)
from stock_platform.database.session import (
    get_session_factory,
)
from stock_platform.realtime.session_models import (
    TradingSessionPhase,
)
from stock_platform.realtime.session_service import (
    RealtimeTradingSessionService,
)


class RealtimeTradingScheduler:
    """KRX 자동매매 세션 시간을 APScheduler로 관리한다."""

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
        self._add_job(
            job_id="realtime_pre_market",
            phase=TradingSessionPhase.PRE_MARKET,
            hour=8,
            minute=50,
        )
        self._add_job(
            job_id="realtime_market_open",
            phase=TradingSessionPhase.MARKET_OPEN,
            hour=9,
            minute=0,
        )
        self._add_job(
            job_id="realtime_market_close",
            phase=TradingSessionPhase.MARKET_CLOSE,
            hour=15,
            minute=20,
        )
        self._add_job(
            job_id="realtime_after_market",
            phase=TradingSessionPhase.AFTER_MARKET,
            hour=15,
            minute=40,
        )

    def start(self) -> None:
        self.configure()
        self._scheduler.start()

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)

    async def run_phase_now(
        self,
        phase: TradingSessionPhase,
    ):
        session = get_session_factory()()
        try:
            return await RealtimeTradingSessionService(
                session
            ).execute(
                phase=phase,
                exchange_code="KRX",
            )
        finally:
            session.close()

    def _add_job(
        self,
        *,
        job_id: str,
        phase: TradingSessionPhase,
        hour: int,
        minute: int,
    ) -> None:
        self._scheduler.add_job(
            self.run_phase_now,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=hour,
                minute=minute,
                timezone=(
                    self._settings.scheduler_timezone
                ),
            ),
            kwargs={"phase": phase},
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )
