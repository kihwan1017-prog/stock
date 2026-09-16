"""STEP N4 — AI News Analysis Scheduler (기본 OFF, concurrency 격리)."""

from __future__ import annotations

import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.news.news_ai_analysis_service import NewsAIAnalysisService


class UpbitNewsAIAnalysisScheduler:
    JOB_ID = "upbit_news_ai_analysis"

    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )
        self._configured = False
        self._started = False
        self._tick_in_progress = False
        self._last_run_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_error: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_duration_ms: int | None = None
        self._run_count = 0
        self._success_count = 0
        self._failure_count = 0

    def enabled(self) -> bool:
        return bool(
            getattr(get_settings(), "upbit_news_ai_analysis_enabled", False)
        )

    def configure(self, *, force: bool = False) -> None:
        if self._configured and not force:
            return
        try:
            self._scheduler.remove_job(self.JOB_ID)
        except Exception:  # noqa: BLE001
            pass
        if not self.enabled():
            self._configured = True
            return
        settings = get_settings()
        interval = max(
            60,
            int(
                getattr(
                    settings, "upbit_news_ai_analysis_interval_seconds", 900
                )
            ),
        )

        async def _tick() -> None:
            await self._run_tick()

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
        if not self.enabled():
            logger.info(
                "upbit_news_ai_analysis_skipped",
                reason="UPBIT_NEWS_AI_ANALYSIS_ENABLED=false",
            )
            self._configured = True
            return
        self.configure(force=True)
        if not self._scheduler.running:
            self._scheduler.start()
            self._started = True
            logger.info("upbit_news_ai_analysis_started")

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._started = False

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        next_run = None
        try:
            job = self._scheduler.get_job(self.JOB_ID)
            if job and job.next_run_time is not None:
                next_run = job.next_run_time.isoformat()
        except Exception:  # noqa: BLE001
            pass
        return {
            "enabled": self.enabled(),
            "running": bool(self._started and self._scheduler.running),
            "interval_seconds": int(
                getattr(
                    settings, "upbit_news_ai_analysis_interval_seconds", 900
                )
            ),
            "batch_size": int(
                getattr(settings, "upbit_news_ai_analysis_batch_size", 5)
            ),
            "model": getattr(settings, "upbit_news_ai_analysis_model", "")
            or settings.ollama_model,
            "last_run": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "last_success": (
                self._last_success_at.isoformat()
                if self._last_success_at
                else None
            ),
            "next_run": next_run,
            "last_error": self._last_error,
            "last_duration_ms": self._last_duration_ms,
            "run_count": self._run_count,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "last_result": self._last_result,
            "max_concurrency": 1,
            "informational_only": True,
        }

    async def run_once_now(
        self,
        *,
        limit: int = 5,
        article_ids: list[int] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        return await self._run_tick(
            limit=limit, article_ids=article_ids, force=force
        )

    async def _run_tick(
        self,
        *,
        limit: int | None = None,
        article_ids: list[int] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        if self._tick_in_progress:
            return {"skipped": True, "reason": "TICK_IN_PROGRESS"}
        self._tick_in_progress = True
        started = time.perf_counter()
        self._last_run_at = datetime.now(timezone.utc)
        self._run_count += 1
        session = get_session_factory()()
        service = NewsAIAnalysisService(session)
        try:
            settings = get_settings()
            batch = limit or int(
                getattr(settings, "upbit_news_ai_analysis_batch_size", 5)
            )
            stats = await service.run_batch(
                limit=batch, article_ids=article_ids, force=force
            )
            result = asdict(stats)
            self._last_result = result
            if stats.failed and not stats.analyzed and not stats.reused:
                self._failure_count += 1
                self._last_error = "batch_failed"
            else:
                self._success_count += 1
                self._last_success_at = datetime.now(timezone.utc)
                self._last_error = None
            return result
        except Exception as exc:  # noqa: BLE001
            self._failure_count += 1
            self._last_error = f"{type(exc).__name__}: {exc}"[:500]
            logger.warning(
                "upbit_news_ai_analysis_tick_failed",
                error=self._last_error,
            )
            return {"failed": 1, "error": self._last_error}
        finally:
            try:
                await service.aclose()
            except Exception:  # noqa: BLE001
                pass
            session.close()
            self._last_duration_ms = int(
                (time.perf_counter() - started) * 1000
            )
            self._tick_in_progress = False


upbit_news_ai_analysis_scheduler = UpbitNewsAIAnalysisScheduler()
