"""STEP N6/N7 — Combined Shadow Experiment Scheduler (DEFAULT OFF)."""

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
from stock_platform.operation.upbit_news_combined_shadow.evaluator import (
    UpbitNewsCombinedShadowEvaluator,
)
from stock_platform.operation.upbit_news_combined_shadow.service import (
    UpbitNewsCombinedShadowService,
)


class UpbitNewsCombinedShadowScheduler:
    JOB_ID = "upbit_news_combined_shadow"

    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )
        self._configured = False
        self._started = False
        self._tick_in_progress = False
        self._last_run_at: datetime | None = None
        self._last_error: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._run_count = 0
        self._overlap_skips = 0

    def enabled(self) -> bool:
        return bool(
            getattr(
                get_settings(), "upbit_news_combined_shadow_enabled", False
            )
        )

    def configure(self, *, force: bool = False) -> None:
        """restart registration: force=True로 job 재등록."""

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
                    settings,
                    "upbit_news_combined_shadow_interval_seconds",
                    900,
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
        logger.info(
            "upbit_news_combined_shadow_job_registered",
            interval_seconds=interval,
            max_instances=1,
        )

    def start(self) -> None:
        if not self.enabled():
            logger.info(
                "upbit_news_combined_shadow_skipped",
                reason="UPBIT_NEWS_COMBINED_SHADOW_ENABLED=false",
            )
            self._configured = True
            return
        self.configure(force=True)
        if not self._scheduler.running:
            self._scheduler.start()
            self._started = True

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._started = False

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        return {
            "job_id": self.JOB_ID,
            "enabled": self.enabled(),
            "started": self._started,
            "default_off": True,
            "manual_vs_auto": "auto_only_when_enabled_env_true",
            "interval_seconds": float(
                getattr(
                    settings,
                    "upbit_news_combined_shadow_interval_seconds",
                    900,
                )
            ),
            "max_instances": 1,
            "overlap_skips": self._overlap_skips,
            "last_run_at": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "last_error": self._last_error,
            "last_result": self._last_result,
            "run_count": self._run_count,
            "llm_calls": 0,
            "experiment_only": True,
            "scanner_hook": False,
            "failure_isolation": True,
        }

    async def _run_tick(self) -> None:
        if self._tick_in_progress:
            self._overlap_skips += 1
            logger.info(
                "upbit_news_combined_shadow_overlap_skipped",
                reason="tick_in_progress",
            )
            return
        if not self.enabled():
            return
        self._tick_in_progress = True
        self._run_count += 1
        self._last_run_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        try:
            session = get_session_factory()()
            try:
                svc = UpbitNewsCombinedShadowService(session)
                stats = svc.run_from_control_shadows(
                    limit_runs=5, force=False, include_memory_top_n=True
                )
                ev = UpbitNewsCombinedShadowEvaluator(session)
                eval_stats = ev.evaluate_pending(limit=50)
                self._last_result = {
                    "run": asdict(stats),
                    "evaluate": eval_stats,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "scanner_hook": False,
                    "failure_isolation": True,
                }
                self._last_error = None
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)[:300]
            logger.warning(
                "upbit_news_combined_shadow_tick_failed",
                error=str(exc)[:200],
                note="scanner_unaffected",
            )
        finally:
            self._tick_in_progress = False


upbit_news_combined_shadow_scheduler = UpbitNewsCombinedShadowScheduler()
