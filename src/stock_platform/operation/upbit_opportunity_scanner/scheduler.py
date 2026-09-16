"""UPBIT Opportunity Scanner Scheduler — SHADOW_ONLY Fail Closed."""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_opportunity_scanner.notify import (
    publish_scanner_failure,
)
from stock_platform.operation.upbit_opportunity_scanner.policy import (
    SCANNER_MODE_SHADOW_ONLY,
    load_scanner_policy,
)


class UpbitOpportunityScannerScheduler:
    JOB_ID = "upbit_opportunity_scanner"
    _DURATION_HISTORY_MAX = 24

    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )
        self._configured = False
        self._started = False
        self._tick_in_progress = False
        self._last_run_at: datetime | None = None
        self._last_completed_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_failure_at: datetime | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._last_duration_ms: int | None = None
        self._last_skip_reason: str | None = None
        self._overlap_skip_count = 0
        self._run_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._duration_history_ms: deque[int] = deque(
            maxlen=self._DURATION_HISTORY_MAX
        )
        # service 인스턴스 재사용 — cooldown 유지
        self._service_holder: Any | None = None

    @staticmethod
    def automation_allowed(policy: Any | None = None) -> tuple[bool, str | None]:
        """enabled + SHADOW_ONLY만 스케줄러 기동 허용."""

        policy = policy if policy is not None else load_scanner_policy()
        if not policy.enabled:
            return False, "UPBIT_OPPORTUNITY_SCANNER_ENABLED=false"
        if str(policy.mode).upper() != SCANNER_MODE_SHADOW_ONLY:
            return False, f"MODE_NOT_SHADOW_ONLY:{policy.mode}"
        return True, None

    def configure(self, *, force: bool = False) -> None:
        if self._configured and not force:
            return
        allowed, reason = self.automation_allowed()
        if not allowed:
            self._configured = True
            self._last_skip_reason = reason
            return

        policy = load_scanner_policy()
        interval = max(60, int(policy.interval_seconds or 900))

        async def _tick() -> None:
            await self._run_tick()

        try:
            self._scheduler.remove_job(self.JOB_ID)
        except Exception:  # noqa: BLE001
            pass
        # max_instances=1 + coalesce + in-process single-flight(_tick_in_progress)
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
        self._last_skip_reason = None

    def start(self) -> None:
        allowed, reason = self.automation_allowed()
        if not allowed:
            logger.info(
                "upbit_opportunity_scanner_skipped",
                reason=reason,
            )
            self._last_skip_reason = reason
            return
        self.configure(force=True)
        if not self._scheduler.running:
            self._scheduler.start()
            self._started = True
            policy = load_scanner_policy()
            logger.info(
                "upbit_opportunity_scanner_started",
                mode=SCANNER_MODE_SHADOW_ONLY,
                interval_seconds=policy.interval_seconds,
                top_n=policy.top_n,
                single_flight=True,
            )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._started = False

    def status(self) -> dict[str, Any]:
        policy = load_scanner_policy()
        allowed, block_reason = self.automation_allowed(policy)
        next_run = None
        job_ids: list[str] = []
        try:
            job = self._scheduler.get_job(self.JOB_ID)
            if job is not None and job.next_run_time is not None:
                next_run = job.next_run_time.isoformat()
            job_ids = [j.id for j in self._scheduler.get_jobs()]
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
                "ai_model": self._last_result.get("ai_model"),
                "ai_reuse_seconds": self._last_result.get("ai_reuse_seconds"),
                "ai_max_inflight": self._last_result.get("ai_max_inflight"),
                "ai_concurrency_configured": self._last_result.get(
                    "ai_concurrency_configured"
                ),
                "ai_symbol_timings": self._last_result.get("ai_symbol_timings"),
                "top_n": len(self._last_result.get("candidates") or []),
                "notifications": self._last_result.get("notifications"),
                "shadow": self._last_result.get("shadow"),
                "scanner_run_id": self._last_result.get("scanner_run_id"),
                "elapsed_ms": self._last_result.get("elapsed_ms"),
                "stage_timings_ms": self._last_result.get("stage_timings_ms"),
                "api_call_counts": self._last_result.get("api_call_counts"),
                "http_429_count": self._last_result.get("http_429_count"),
                "timeout_count": self._last_result.get("timeout_count"),
                "failed_symbol_count": self._last_result.get(
                    "failed_symbol_count"
                ),
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
        hist = list(self._duration_history_ms)
        hist_stats = None
        if hist:
            ordered = sorted(hist)
            p95_idx = min(
                len(ordered) - 1, max(0, int(0.95 * len(ordered)) - 1)
            )
            hist_stats = {
                "n": len(ordered),
                "min_ms": ordered[0],
                "median_ms": ordered[len(ordered) // 2],
                "p95_ms": ordered[p95_idx],
                "max_ms": ordered[-1],
            }
        return {
            "enabled": policy.enabled,
            "mode": policy.mode,
            "automation_allowed": allowed,
            "block_reason": block_reason,
            "running": bool(self._scheduler.running),
            "started": self._started,
            "tick_in_progress": self._tick_in_progress,
            "single_flight": True,
            "skip_if_running": True,
            "interval_seconds": policy.interval_seconds,
            "candle_concurrency": policy.candle_concurrency,
            "ai_concurrency": policy.ai_concurrency,
            "top_n": policy.top_n,
            "min_24h_trade_value_krw": policy.min_24h_trade_value_krw,
            "job_id": self.JOB_ID,
            "job_ids": job_ids,
            "last_run_at": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "last_completed_at": (
                self._last_completed_at.isoformat()
                if self._last_completed_at
                else None
            ),
            "next_run_at": next_run,
            "last_duration_ms": self._last_duration_ms,
            "duration_history_ms": hist,
            "duration_stats": hist_stats,
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
            "last_skip_reason": self._last_skip_reason,
            "overlap_skip_count": self._overlap_skip_count,
            "skipped_overlap": self._overlap_skip_count,
            "run_count": self._run_count,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "last_result_summary": summary,
            "shadow_only": True,
            "alert_only": True,
            "live_auto_start": False,
            "live_order": False,
            "orders_created": 0,
        }

    async def run_once_now(
        self,
        *,
        notify: bool = True,
        force_ai: bool = False,
    ) -> dict[str, Any]:
        """운영 Dry Run / 수동 1회 (실주문 없음). enabled와 무관."""

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

        if self._tick_in_progress:
            self._overlap_skip_count += 1
            self._last_skip_reason = "OVERLAP_SKIP"
            logger.info(
                "upbit_opportunity_scanner_overlap_skip",
                overlap_skip_count=self._overlap_skip_count,
            )
            return {
                "ok": False,
                "skipped": True,
                "code": "OVERLAP_SKIP",
                "orders_created": 0,
                "shadow_only": True,
                "live_order": False,
            }

        self._tick_in_progress = True
        now = datetime.now(timezone.utc)
        self._last_run_at = now
        self._run_count += 1
        started = time.perf_counter()
        Session = get_session_factory()
        try:
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
                    result["shadow_only"] = True
                    result["live_order"] = False
                    result.setdefault("orders_created", 0)
                    self._last_result = result
                    self._last_duration_ms = int(
                        (time.perf_counter() - started) * 1000
                    )
                    result["duration_ms"] = self._last_duration_ms
                    self._duration_history_ms.append(self._last_duration_ms)
                    self._last_completed_at = datetime.now(timezone.utc)
                    if result.get("ok"):
                        self._last_success_at = datetime.now(timezone.utc)
                        self._success_count += 1
                        self._last_error = None
                        t_sel = time.perf_counter()
                        try:
                            from stock_platform.common.settings import (
                                get_settings as _gs,
                            )

                            if bool(
                                getattr(
                                    _gs(),
                                    "upbit_full_market_consume_after_scanner",
                                    True,
                                )
                            ):
                                from stock_platform.operation.upbit_full_market.consume import (
                                    consume_latest_scanner_for_full_market_accounts,
                                )

                                consume_out = (
                                    consume_latest_scanner_for_full_market_accounts(
                                        session,
                                        scanner_result=result,
                                        dry_run=False,
                                    )
                                )
                                result["full_market_consume"] = consume_out
                                session.commit()
                        except Exception as consume_exc:  # noqa: BLE001
                            logger.warning(
                                "upbit_full_market_consume_hook_failed",
                                error=type(consume_exc).__name__,
                            )
                            try:
                                session.rollback()
                            except Exception:  # noqa: BLE001
                                pass
                        if isinstance(result.get("stage_timings_ms"), dict):
                            result["stage_timings_ms"]["LIVE_SELECTION_MS"] = (
                                int((time.perf_counter() - t_sel) * 1000)
                            )
                    else:
                        self._last_failure_at = datetime.now(timezone.utc)
                        self._failure_count += 1
                        errs = result.get("errors") or []
                        self._last_error = (
                            str(errs[0]) if errs else "SCANNER_FAILED"
                        )
                        if notify:
                            publish_scanner_failure(
                                error=self._last_error,
                                detail={
                                    "duration_ms": self._last_duration_ms,
                                    "errors": errs,
                                },
                            )
                    return result
                except Exception as exc:  # noqa: BLE001
                    session.rollback()
                    self._last_failure_at = datetime.now(timezone.utc)
                    self._failure_count += 1
                    self._last_error = type(exc).__name__
                    self._last_duration_ms = int(
                        (time.perf_counter() - started) * 1000
                    )
                    self._duration_history_ms.append(self._last_duration_ms)
                    self._last_completed_at = datetime.now(timezone.utc)
                    logger.warning(
                        "upbit_opportunity_scanner_tick_failed",
                        error=type(exc).__name__,
                    )
                    if notify:
                        publish_scanner_failure(
                            error=type(exc).__name__,
                            detail={
                                "duration_ms": self._last_duration_ms,
                                "message": str(exc)[:200],
                            },
                        )
                    return {
                        "ok": False,
                        "error": type(exc).__name__,
                        "orders_created": 0,
                        "shadow_only": True,
                        "live_order": False,
                        "alert_only": True,
                        "duration_ms": self._last_duration_ms,
                    }
        finally:
            self._tick_in_progress = False


upbit_opportunity_scanner_scheduler = UpbitOpportunityScannerScheduler()
