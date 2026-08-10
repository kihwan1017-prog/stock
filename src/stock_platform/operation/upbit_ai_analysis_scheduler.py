"""UPBIT autotrading AI Market Analysis 주기 스케줄러 (APScheduler).

AI Gate LIVE ON / Runtime / 실주문과 무관.
enabled 플래그가 OFF면 기동하지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory


class UpbitAutotradingAiAnalysisScheduler:
    JOB_ID = "upbit_autotrading_ai_analysis"

    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )
        self._configured = False
        self._started = False
        self._last_run_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_failure_at: datetime | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._run_count = 0
        self._success_count = 0
        self._failure_count = 0

    def configure(self, *, force: bool = False) -> None:
        if self._configured and not force:
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

        # 중복 job 방지 — 동일 id replace
        self._scheduler.add_job(
            _tick,
            IntervalTrigger(seconds=interval),
            id=self.JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(interval, 60),
        )
        self._configured = True

    def start(self) -> None:
        settings = get_settings()
        if not bool(
            getattr(settings, "autotrading_ai_analysis_enabled", False)
        ):
            logger.info(
                "upbit_autotrading_ai_analysis_scheduler_skipped",
                reason="AUTOTRADING_AI_ANALYSIS_ENABLED=false",
            )
            return
        # enabled 전환 후에도 job 등록되도록 force configure
        self.configure(force=True)
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

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        next_run = None
        try:
            job = self._scheduler.get_job(self.JOB_ID)
            if job is not None and job.next_run_time is not None:
                next_run = job.next_run_time.isoformat()
        except Exception:  # noqa: BLE001
            next_run = None

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
            "last_run_at": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "next_run_at": next_run,
            "last_success_at": (
                self._last_success_at.isoformat()
                if self._last_success_at
                else None
            ),
            "last_failure_at": (
                self._last_failure_at.isoformat()
                if self._last_failure_at
                else None
            ),
            "last_error": self._last_error,
            "run_count": self._run_count,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "last_result_summary": {
                "ok": (self._last_result or {}).get("ok"),
                "skipped": (self._last_result or {}).get("skipped"),
                "skip_reason": (self._last_result or {}).get("skip_reason"),
                "market_analysis_id": (self._last_result or {}).get(
                    "market_analysis_id"
                ),
                "recommendation": (self._last_result or {}).get(
                    "recommendation"
                ),
                "external_ai_called": (self._last_result or {}).get(
                    "external_ai_called"
                ),
            }
            if self._last_result
            else None,
            "duplicate_job_policy": "replace_existing + max_instances=1",
        }

    async def run_once_now(self, *, force: bool = False) -> dict[str, Any]:
        """운영 검증용 즉시 1회 실행 (실주문 없음)."""

        return await self._run_tick(force=force)

    async def _run_tick(self, *, force: bool = False) -> dict[str, Any]:
        from stock_platform.ai.market_analysis.autotrading_periodic import (
            UpbitAutotradingAiAnalysisJob,
        )

        now = datetime.now(timezone.utc)
        self._last_run_at = now
        self._run_count += 1
        Session = get_session_factory()
        with Session() as session:
            try:
                result = await UpbitAutotradingAiAnalysisJob(session).run_once(
                    force=force
                )
                self._last_result = result
                ok = bool(result.get("ok")) or bool(result.get("skipped"))
                if ok:
                    self._last_success_at = datetime.now(timezone.utc)
                    self._success_count += 1
                    self._last_error = None
                else:
                    self._last_failure_at = datetime.now(timezone.utc)
                    self._failure_count += 1
                    self._last_error = str(result.get("error") or "FAILED")[:300]
                logger.info(
                    "upbit_autotrading_ai_analysis_tick",
                    ok=result.get("ok"),
                    skipped=result.get("skipped"),
                    skip_reason=result.get("skip_reason"),
                    analysis_id=result.get("market_analysis_id"),
                    recommendation=result.get("recommendation"),
                    external_ai_called=result.get("external_ai_called"),
                )
                return result
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                self._last_failure_at = datetime.now(timezone.utc)
                self._failure_count += 1
                self._last_error = f"{type(exc).__name__}:{str(exc)[:200]}"
                logger.warning(
                    "upbit_autotrading_ai_analysis_tick_failed",
                    error=type(exc).__name__,
                    detail=str(exc)[:300],
                )
                return {
                    "ok": False,
                    "error": self._last_error,
                    "orders_created": 0,
                }


upbit_autotrading_ai_analysis_scheduler = (
    UpbitAutotradingAiAnalysisScheduler()
)
