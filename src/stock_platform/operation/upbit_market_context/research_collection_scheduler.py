"""Upbit Market Context Research Collection Scheduler (APScheduler).

Market/Asset snapshot 주기 수집 + Fear&Greed 별도 cadence.
CLEAN Forward / REAL 주문 / LIVE·ARM 과 무관. failure isolated.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory


class UpbitMarketContextResearchScheduler:
    """연구용 market/asset context 자동 수집."""

    MARKET_JOB_ID = "upbit_market_context_research_collect"
    FNG_JOB_ID = "upbit_market_context_fear_greed"

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
        self._last_failure_at: datetime | None = None
        self._last_error: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_duration_ms: int | None = None
        self._last_fng_at: datetime | None = None
        self._run_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._overlap_skip_count = 0

    def enabled(self) -> bool:
        return bool(
            getattr(
                get_settings(),
                "upbit_market_context_collection_enabled",
                True,
            )
        )

    def market_interval_seconds(self) -> int:
        return max(
            60,
            int(
                getattr(
                    get_settings(),
                    "upbit_market_context_collection_interval_seconds",
                    600,
                )
                or 600
            ),
        )

    def asset_interval_seconds(self) -> int:
        # Asset는 market tick과 동일 job에서 수집
        return self.market_interval_seconds()

    def fng_interval_seconds(self) -> int:
        return max(
            300,
            int(
                getattr(
                    get_settings(),
                    "upbit_market_context_fng_interval_seconds",
                    3600,
                )
                or 3600
            ),
        )

    def configure(self, *, force: bool = False) -> None:
        if self._configured and not force:
            return

        for job_id in (self.MARKET_JOB_ID, self.FNG_JOB_ID):
            try:
                self._scheduler.remove_job(job_id)
            except Exception:  # noqa: BLE001
                pass

        if not self.enabled():
            self._configured = True
            return

        market_iv = self.market_interval_seconds()
        fng_iv = self.fng_interval_seconds()

        async def _market_tick() -> None:
            await self._run_tick(include_fear_greed=False, source="market")

        async def _fng_tick() -> None:
            # F&G만 별도 — rate limit 준수. market metrics도 함께 갱신해도 무해.
            await self._run_tick(include_fear_greed=True, source="fear_greed")

        self._scheduler.add_job(
            _market_tick,
            IntervalTrigger(seconds=market_iv),
            id=self.MARKET_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(market_iv, 60),
        )
        self._scheduler.add_job(
            _fng_tick,
            IntervalTrigger(seconds=fng_iv),
            id=self.FNG_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(fng_iv, 60),
        )
        self._configured = True

    def start(self) -> None:
        if not self.enabled():
            logger.info(
                "upbit_market_context_research_scheduler_skipped",
                reason="UPBIT_MARKET_CONTEXT_COLLECTION_ENABLED=false",
            )
            self._configured = True
            return
        self.configure(force=True)
        if not self._scheduler.running:
            self._scheduler.start()
            self._started = True
            logger.info(
                "upbit_market_context_research_scheduler_started",
                market_interval_seconds=self.market_interval_seconds(),
                fng_interval_seconds=self.fng_interval_seconds(),
            )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._started = False

    def status(self) -> dict[str, Any]:
        next_market = None
        next_fng = None
        job_ids: list[str] = []
        try:
            job = self._scheduler.get_job(self.MARKET_JOB_ID)
            if job is not None and job.next_run_time is not None:
                next_market = job.next_run_time.isoformat()
            job_f = self._scheduler.get_job(self.FNG_JOB_ID)
            if job_f is not None and job_f.next_run_time is not None:
                next_fng = job_f.next_run_time.isoformat()
            job_ids = [j.id for j in self._scheduler.get_jobs()]
        except Exception:  # noqa: BLE001
            pass

        return {
            "enabled": self.enabled(),
            "running": bool(self._started and self._scheduler.running),
            "started": self._started,
            "tick_in_progress": self._tick_in_progress,
            "market_interval_seconds": self.market_interval_seconds(),
            "asset_interval_seconds": self.asset_interval_seconds(),
            "fng_interval_seconds": self.fng_interval_seconds(),
            "job_ids": job_ids,
            "jobs": [
                {
                    "id": self.MARKET_JOB_ID,
                    "interval_seconds": self.market_interval_seconds(),
                    "next_run_at": next_market,
                },
                {
                    "id": self.FNG_JOB_ID,
                    "interval_seconds": self.fng_interval_seconds(),
                    "next_run_at": next_fng,
                },
            ],
            "next_run_at": next_market or next_fng,
            "last_run_at": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
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
            "last_fng_at": (
                self._last_fng_at.isoformat() if self._last_fng_at else None
            ),
            "last_error": self._last_error,
            "last_duration_ms": self._last_duration_ms,
            "run_count": self._run_count,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "overlap_skip_count": self._overlap_skip_count,
            "last_result": self._last_result,
            "research_only": True,
            "live_order": False,
            "creates_clean_forward": False,
        }

    async def run_once_now(
        self, *, include_fear_greed: bool = True
    ) -> dict[str, Any]:
        return await self._run_tick(
            include_fear_greed=include_fear_greed, source="manual"
        )

    async def _run_tick(
        self, *, include_fear_greed: bool, source: str
    ) -> dict[str, Any]:
        if self._tick_in_progress:
            self._overlap_skip_count += 1
            return {
                "ok": False,
                "skipped": True,
                "code": "OVERLAP_SKIP",
                "live_order": False,
            }

        self._tick_in_progress = True
        self._last_run_at = datetime.now(timezone.utc)
        self._run_count += 1
        started = time.perf_counter()
        Session = get_session_factory()
        try:
            with Session() as session:
                try:
                    from stock_platform.operation.upbit_market_context.collect_runner import (
                        run_market_context_collect,
                    )

                    out = run_market_context_collect(
                        session,
                        include_fear_greed=include_fear_greed,
                        description_limit=None,
                    )
                    session.commit()
                    self._last_duration_ms = int(
                        (time.perf_counter() - started) * 1000
                    )
                    result = {
                        "ok": True,
                        "source": source,
                        "duration_ms": self._last_duration_ms,
                        **out,
                    }
                    self._last_result = {
                        "ok": True,
                        "source": source,
                        "ticker_count": out.get("ticker_count"),
                        "saved": (out.get("result") or {}).get("saved"),
                        "include_fear_greed": include_fear_greed,
                    }
                    self._last_success_at = datetime.now(timezone.utc)
                    if include_fear_greed:
                        self._last_fng_at = self._last_success_at
                    self._success_count += 1
                    self._last_error = None
                    return result
                except Exception as exc:  # noqa: BLE001
                    session.rollback()
                    self._last_failure_at = datetime.now(timezone.utc)
                    self._failure_count += 1
                    self._last_error = type(exc).__name__
                    self._last_duration_ms = int(
                        (time.perf_counter() - started) * 1000
                    )
                    logger.warning(
                        "upbit_market_context_research_tick_failed",
                        error=type(exc).__name__,
                        detail=str(exc)[:200],
                        source=source,
                    )
                    # fail-open — REAL trading path 차단 금지
                    return {
                        "ok": False,
                        "error": type(exc).__name__,
                        "detail": str(exc)[:200],
                        "source": source,
                        "live_order": False,
                        "REAL_POLICY_CHANGED": "NO",
                        "research_failed_open": True,
                    }
        finally:
            self._tick_in_progress = False


upbit_market_context_research_scheduler = UpbitMarketContextResearchScheduler()
