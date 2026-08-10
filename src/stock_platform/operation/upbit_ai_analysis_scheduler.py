"""UPBIT autotrading AI Market Analysis 주기 스케줄러 (APScheduler).

AI Gate LIVE ON / Runtime / 실주문과 무관.
enabled 플래그가 OFF면 기동하지 않는다.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory


class UpbitAutotradingAiAnalysisScheduler:
    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )
        self._configured = False
        self._started = False

    def configure(self) -> None:
        if self._configured:
            return
        settings = get_settings()
        if not bool(
            getattr(settings, "autotrading_ai_analysis_enabled", False)
        ):
            self._configured = True
            return

        interval = max(
            60,
            int(
                getattr(
                    settings,
                    "autotrading_ai_analysis_interval_seconds",
                    300,
                )
                or 300
            ),
        )

        async def _tick() -> None:
            await self._run_tick()

        self._scheduler.add_job(
            _tick,
            IntervalTrigger(seconds=interval),
            id="upbit_autotrading_ai_analysis",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(interval, 60),
        )
        self._configured = True

    def start(self) -> None:
        self.configure()
        settings = get_settings()
        if not bool(
            getattr(settings, "autotrading_ai_analysis_enabled", False)
        ):
            logger.info(
                "upbit_autotrading_ai_analysis_scheduler_skipped",
                reason="AUTOTRADING_AI_ANALYSIS_ENABLED=false",
            )
            return
        if not self._scheduler.running:
            self._scheduler.start()
            self._started = True
            logger.info(
                "upbit_autotrading_ai_analysis_scheduler_started",
                interval_seconds=getattr(
                    settings,
                    "autotrading_ai_analysis_interval_seconds",
                    300,
                ),
                symbol=getattr(
                    settings,
                    "autotrading_ai_analysis_symbol",
                    "KRW-XRP",
                ),
                provider=getattr(
                    settings,
                    "autotrading_ai_analysis_provider",
                    "ollama",
                ),
            )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._started = False

    def status(self) -> dict:
        settings = get_settings()
        return {
            "enabled": bool(
                getattr(settings, "autotrading_ai_analysis_enabled", False)
            ),
            "running": bool(self._scheduler.running),
            "started": self._started,
            "interval_seconds": getattr(
                settings, "autotrading_ai_analysis_interval_seconds", 300
            ),
            "symbol": getattr(
                settings, "autotrading_ai_analysis_symbol", "KRW-XRP"
            ),
            "provider": getattr(
                settings, "autotrading_ai_analysis_provider", "ollama"
            ),
            "model": getattr(
                settings, "autotrading_ai_analysis_model", ""
            )
            or getattr(settings, "ollama_model", "qwen3.5:4b"),
        }

    async def _run_tick(self) -> None:
        from stock_platform.ai.market_analysis.autotrading_periodic import (
            UpbitAutotradingAiAnalysisJob,
        )

        Session = get_session_factory()
        with Session() as session:
            try:
                result = await UpbitAutotradingAiAnalysisJob(session).run_once()
                logger.info(
                    "upbit_autotrading_ai_analysis_tick",
                    ok=result.get("ok"),
                    skipped=result.get("skipped"),
                    skip_reason=result.get("skip_reason"),
                    analysis_id=result.get("market_analysis_id"),
                    recommendation=result.get("recommendation"),
                    external_ai_called=result.get("external_ai_called"),
                )
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                logger.warning(
                    "upbit_autotrading_ai_analysis_tick_failed",
                    error=type(exc).__name__,
                    detail=str(exc)[:300],
                )


upbit_autotrading_ai_analysis_scheduler = (
    UpbitAutotradingAiAnalysisScheduler()
)
