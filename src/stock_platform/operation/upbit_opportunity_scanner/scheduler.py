"""UPBIT Opportunity Scanner Scheduler — enabled=false면 기동하지 않음."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_opportunity_scanner.policy import (
    load_scanner_policy,
)


class UpbitOpportunityScannerScheduler:
    JOB_ID = "upbit_opportunity_scanner"

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
        # service 인스턴스 재사용 — cooldown 유지
        self._service_holder: Any | None = None

    def configure(self, *, force: bool = False) -> None:
        if self._configured and not force:
            return
        settings = get_settings()
        policy = load_scanner_policy(settings)
        if not policy.enabled:
            self._configured = True
            return

        interval = max(60, int(policy.interval_seconds or 900))

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
        policy = load_scanner_policy()
        if not policy.enabled:
            logger.info(
                "upbit_opportunity_scanner_skipped",
                reason="UPBIT_OPPORTUNITY_SCANNER_ENABLED=false",
            )
            return
        self.configure(force=True)
        if not self._scheduler.running:
            self._scheduler.start()
            self._started = True
            logger.info(
                "upbit_opportunity_scanner_started",
                interval_seconds=policy.interval_seconds,
                top_n=policy.top_n,
            )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._started = False

    def status(self) -> dict[str, Any]:
        policy = load_scanner_policy()
        next_run = None
        try:
            job = self._scheduler.get_job(self.JOB_ID)
            if job is not None and job.next_run_time is not None:
                next_run = job.next_run_time.isoformat()
        except Exception:  # noqa: BLE001
            next_run = None
        summary = None
        if self._last_result:
            summary = {
                "ok": self._last_result.get("ok"),
                "universe_count": self._last_result.get("universe_count"),
                "liquidity_pass_count": self._last_result.get(
                    "liquidity_pass_count"
                ),
                "technical_candidate_count": self._last_result.get(
                    "technical_candidate_count"
                ),
                "ai_calls": self._last_result.get("ai_calls"),
                "ai_failed_skipped": self._last_result.get(
                    "ai_failed_skipped"
                ),
                "top_n": len(self._last_result.get("candidates") or []),
                "notifications": self._last_result.get("notifications"),
                "shadow": self._last_result.get("shadow"),
                "scanner_run_id": self._last_result.get("scanner_run_id"),
                "elapsed_ms": self._last_result.get("elapsed_ms"),
                "candidates": [
                    {
                        "rank": c.get("rank"),
                        "symbol": c.get("symbol"),
                        "score": c.get("score"),
                        "recommendation": c.get("recommendation"),
                        "confidence": c.get("confidence"),
                        "risk_level": c.get("risk_level"),
                        "fail_closed": c.get("fail_closed"),
                    }
                    for c in (self._last_result.get("candidates") or [])
                ],
            }
        return {
            "enabled": policy.enabled,
            "running": bool(self._scheduler.running),
            "started": self._started,
            "interval_seconds": policy.interval_seconds,
            "top_n": policy.top_n,
            "min_24h_trade_value_krw": policy.min_24h_trade_value_krw,
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
            "last_result_summary": summary,
            "alert_only": True,
            "live_auto_start": False,
        }

    async def run_once_now(
        self,
        *,
        notify: bool = True,
        force_ai: bool = False,
    ) -> dict[str, Any]:
        """운영 Dry Run / 수동 1회 (실주문 없음)."""

        return await self._run_tick(notify=notify, force_ai=force_ai)

    async def _run_tick(
        self,
        *,
        notify: bool = True,
        force_ai: bool = False,
    ) -> dict[str, Any]:
        from stock_platform.operation.upbit_opportunity_scanner.service import (
            UpbitOpportunityScannerService,
        )

        now = datetime.now(timezone.utc)
        self._last_run_at = now
        self._run_count += 1
        Session = get_session_factory()
        with Session() as session:
            try:
                if self._service_holder is None:
                    self._service_holder = UpbitOpportunityScannerService(
                        session
                    )
                else:
                    # session 교체
                    self._service_holder._session = session  # noqa: SLF001
                result = await self._service_holder.run(
                    notify=notify,
                    force_ai=force_ai,
                )
                self._last_result = result
                if result.get("ok"):
                    self._last_success_at = datetime.now(timezone.utc)
                    self._success_count += 1
                    self._last_error = None
                else:
                    self._last_failure_at = datetime.now(timezone.utc)
                    self._failure_count += 1
                    errs = result.get("errors") or []
                    self._last_error = (
                        str(errs[0]) if errs else "SCANNER_FAILED"
                    )
                return result
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                self._last_failure_at = datetime.now(timezone.utc)
                self._failure_count += 1
                self._last_error = type(exc).__name__
                logger.warning(
                    "upbit_opportunity_scanner_tick_failed",
                    error=type(exc).__name__,
                )
                return {
                    "ok": False,
                    "error": type(exc).__name__,
                    "orders_created": 0,
                    "alert_only": True,
                }


upbit_opportunity_scanner_scheduler = UpbitOpportunityScannerScheduler()
