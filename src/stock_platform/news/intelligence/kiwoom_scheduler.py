"""KIWOOM TOP10 News/DART collector scheduler — failure isolated."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.news.intelligence.kiwoom_collector import (
    KiwoomTop10NewsDartCollector,
    result_as_dict,
)
from stock_platform.news.intelligence.pipeline_hooks import (
    after_kiwoom_collect_tick,
)


class KiwoomTop10NewsDartScheduler:
    NEWS_JOB_ID = "kiwoom_top10_news_collection"
    DART_JOB_ID = "kiwoom_top10_dart_collection"

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
        self._overlap_skip_count = 0

    def news_enabled(self) -> bool:
        return bool(
            getattr(get_settings(), "kiwoom_top10_news_collection_enabled", True)
        )

    def dart_enabled(self) -> bool:
        return bool(
            getattr(get_settings(), "kiwoom_top10_dart_collection_enabled", True)
        )

    def configure(self, *, force: bool = False) -> None:
        if self._configured and not force:
            return
        settings = get_settings()
        for job_id in (self.NEWS_JOB_ID, self.DART_JOB_ID):
            try:
                self._scheduler.remove_job(job_id)
            except Exception:  # noqa: BLE001
                pass

        if self.news_enabled():
            interval = max(
                120,
                int(
                    getattr(
                        settings,
                        "kiwoom_top10_news_collection_interval_seconds",
                        900,
                    )
                ),
            )

            async def _news_tick() -> None:
                await self._run_tick(include_news=True, include_dart=False)

            self._scheduler.add_job(
                _news_tick,
                IntervalTrigger(seconds=interval),
                id=self.NEWS_JOB_ID,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=max(interval, 60),
            )

        if self.dart_enabled():
            interval = max(
                300,
                int(
                    getattr(
                        settings,
                        "kiwoom_top10_dart_collection_interval_seconds",
                        1800,
                    )
                ),
            )

            async def _dart_tick() -> None:
                await self._run_tick(include_news=False, include_dart=True)

            self._scheduler.add_job(
                _dart_tick,
                IntervalTrigger(seconds=interval),
                id=self.DART_JOB_ID,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=max(interval, 60),
            )
        self._configured = True

    def start(self) -> None:
        self.configure()
        if not (self.news_enabled() or self.dart_enabled()):
            self._started = False
            return
        if not self._scheduler.running:
            self._scheduler.start()
        self._started = True
        logger.info(
            "kiwoom_top10_news_dart_scheduler_started",
            news=self.news_enabled(),
            dart=self.dart_enabled(),
        )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._started = False

    def status(self) -> dict[str, Any]:
        next_news = None
        next_dart = None
        try:
            job = self._scheduler.get_job(self.NEWS_JOB_ID)
            if job and job.next_run_time is not None:
                next_news = job.next_run_time.isoformat()
        except Exception:  # noqa: BLE001
            pass
        try:
            job = self._scheduler.get_job(self.DART_JOB_ID)
            if job and job.next_run_time is not None:
                next_dart = job.next_run_time.isoformat()
        except Exception:  # noqa: BLE001
            pass
        last = self._last_result or {}
        return {
            "enabled": self.news_enabled() or self.dart_enabled(),
            "running": bool(self._started and self._scheduler.running),
            "tick_in_progress": self._tick_in_progress,
            "last_check_at": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "last_success_at": (
                self._last_success_at.isoformat()
                if self._last_success_at
                else None
            ),
            "last_new_item_at": last.get("last_new_article_at"),
            "last_run": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "last_success": (
                self._last_success_at.isoformat()
                if self._last_success_at
                else None
            ),
            "next_run": next_news or next_dart,
            "sources": {
                "KIWOOM_TOP10_NEWS": {
                    "enabled": self.news_enabled(),
                    "next_run": next_news,
                },
                "KIWOOM_TOP10_DART": {
                    "enabled": self.dart_enabled(),
                    "next_run": next_dart,
                },
            },
            "run_count": self._run_count,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "overlap_skip_count": self._overlap_skip_count,
            "last_error": self._last_error,
            "last_duration_ms": self._last_duration_ms,
            "last_result": self._last_result,
            "isolation": {
                "real_fresh_golden_cross": "unaffected",
                "kiwoom_live_arm": "unaffected",
                "upbit_runtime": "unaffected",
            },
        }

    async def run_once_now(
        self,
        *,
        include_news: bool = True,
        include_dart: bool = True,
    ) -> dict[str, Any]:
        return await self._run_tick(
            include_news=include_news,
            include_dart=include_dart,
            force=True,
        )

    async def _run_tick(
        self,
        *,
        include_news: bool,
        include_dart: bool,
        force: bool = False,
    ) -> dict[str, Any]:
        if self._tick_in_progress:
            self._overlap_skip_count += 1
            return {"skipped": True, "reason": "TICK_IN_PROGRESS"}

        self._tick_in_progress = True
        started = time.perf_counter()
        self._last_run_at = datetime.now(timezone.utc)
        self._run_count += 1
        session = get_session_factory()()
        try:
            collector = KiwoomTop10NewsDartCollector(session)
            result = await collector.collect(
                include_news=include_news,
                include_dart=include_dart,
            )
            payload = result_as_dict(result)
            if result.last_error and result.news_synced == 0 and result.dart_synced == 0:
                self._failure_count += 1
                self._last_error = result.last_error
            else:
                self._success_count += 1
                self._last_success_at = datetime.now(timezone.utc)
                self._last_error = result.last_error
            try:
                payload["intelligence"] = after_kiwoom_collect_tick(payload)
            except Exception as hook_exc:  # noqa: BLE001
                payload["intelligence"] = {
                    "ok": False,
                    "error": f"{type(hook_exc).__name__}: {hook_exc}"[:300],
                }
            self._last_result = payload
            return payload
        except Exception as exc:  # noqa: BLE001
            self._failure_count += 1
            self._last_error = f"{type(exc).__name__}: {exc}"[:500]
            logger.warning(
                "kiwoom_top10_news_dart_tick_failed",
                error=self._last_error,
            )
            payload = {"failure_count": 1, "last_error": self._last_error}
            self._last_result = payload
            return payload
        finally:
            self._last_duration_ms = int((time.perf_counter() - started) * 1000)
            self._tick_in_progress = False
            session.close()


kiwoom_top10_news_dart_scheduler = KiwoomTop10NewsDartScheduler()
