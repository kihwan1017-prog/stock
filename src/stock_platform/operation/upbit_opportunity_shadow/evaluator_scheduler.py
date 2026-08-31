"""ACTIVE Shadow 평가 주기 스케줄러 — SHADOW ONLY, 실주문 0."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory

SCANNER_MODE_SHADOW_ONLY = "SHADOW_ONLY"


class UpbitOpportunityShadowEvaluatorScheduler:
    JOB_ID = "upbit_opportunity_shadow_evaluator"

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
        self._last_duration_ms: int | None = None
        self._last_result: dict[str, Any] | None = None
        self._overlap_skip_count = 0
        self._run_count = 0
        self._success_count = 0
        self._failure_count = 0

    @staticmethod
    def automation_allowed(settings: Any | None = None) -> tuple[bool, str | None]:
        settings = settings if settings is not None else get_settings()
        if not bool(getattr(settings, "upbit_scanner_shadow_enabled", True)):
            return False, "SHADOW_DISABLED"
        eval_on = bool(
            getattr(settings, "upbit_scanner_shadow_evaluator_enabled", True)
        )
        scanner_enabled = bool(
            getattr(settings, "upbit_opportunity_scanner_enabled", False)
        )
        mode = str(
            getattr(settings, "upbit_opportunity_scanner_mode", SCANNER_MODE_SHADOW_ONLY)
            or SCANNER_MODE_SHADOW_ONLY
        ).strip().upper()
        scanner_on = (
            scanner_enabled and mode == SCANNER_MODE_SHADOW_ONLY
        )
        if eval_on or scanner_on:
            return True, None
        return False, "EVALUATOR_DISABLED"

    def configure(self, *, force: bool = False) -> None:
        if self._configured and not force:
            return
        allowed, reason = self.automation_allowed()
        if not allowed:
            self._configured = True
            return

        settings = get_settings()
        interval = int(
            getattr(
                settings, "upbit_scanner_shadow_evaluator_interval_seconds", 180
            )
            or 180
        )
        # 1~5분 권장 범위 클램프
        interval = max(60, min(300, interval))

        async def _tick() -> None:
            await self._run_tick()

        try:
            self._scheduler.remove_job(self.JOB_ID)
        except Exception:  # noqa: BLE001
            pass
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
        try:
            from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.scheduler import (
                UpbitMaExitForwardShadowScheduler,
            )

            UpbitMaExitForwardShadowScheduler().configure(self._scheduler)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ma_exit_forward_shadow_scheduler_configure_failed",
                error=str(exc)[:200],
            )
        try:
            from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.scheduler import (
                UpbitEntrySignalShadowOutcomeScheduler,
            )

            UpbitEntrySignalShadowOutcomeScheduler().configure(self._scheduler)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "entry_signal_shadow_outcome_scheduler_configure_failed",
                error=str(exc)[:200],
            )
        try:
            from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.scheduler import (
                KiwoomEntrySignalShadowOutcomeScheduler,
            )

            KiwoomEntrySignalShadowOutcomeScheduler().configure(self._scheduler)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "kiwoom_entry_signal_shadow_outcome_scheduler_configure_failed",
                error=str(exc)[:200],
            )
        try:
            from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.scheduler import (
                UpbitTrailingForwardShadowScheduler,
            )

            UpbitTrailingForwardShadowScheduler().configure(self._scheduler)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "trailing_forward_shadow_scheduler_configure_failed",
                error=str(exc)[:200],
            )
        try:
            from stock_platform.operation.upbit_h2_h3_forward_shadow.scheduler import (
                UpbitH2H3ForwardShadowScheduler,
            )

            UpbitH2H3ForwardShadowScheduler().configure(self._scheduler)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "h2_h3_forward_shadow_scheduler_configure_failed",
                error=str(exc)[:200],
            )
        try:
            from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.scheduler import (
                UpbitExitStrategyShadowScheduler,
            )

            UpbitExitStrategyShadowScheduler().configure(self._scheduler)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "exit_strategy_shadow_scheduler_configure_failed",
                error=str(exc)[:200],
            )
        try:
            from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.scheduler import (
                UpbitWaitingLifecycleShadowScheduler,
            )

            UpbitWaitingLifecycleShadowScheduler().configure(self._scheduler)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "waiting_lifecycle_shadow_scheduler_configure_failed",
                error=str(exc)[:200],
            )

    def start(self) -> None:
        """lifecycle 진입점 — configure 후 AsyncIOScheduler 기동."""

        allowed, reason = self.automation_allowed()
        if not allowed:
            logger.info(
                "upbit_shadow_evaluator_skipped",
                reason=reason,
            )
            return
        self.configure(force=True)
        if not self._scheduler.running:
            self._scheduler.start()
            self._started = True
            settings = get_settings()
            logger.info(
                "upbit_shadow_evaluator_started",
                interval_seconds=getattr(
                    settings,
                    "upbit_scanner_shadow_evaluator_interval_seconds",
                    180,
                ),
                mode=SCANNER_MODE_SHADOW_ONLY,
                job_ids=[j.id for j in self._scheduler.get_jobs()],
            )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._started = False

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        allowed, block_reason = self.automation_allowed(settings)
        interval = int(
            getattr(
                settings, "upbit_scanner_shadow_evaluator_interval_seconds", 180
            )
            or 180
        )
        interval = max(60, min(300, interval))
        next_run = None
        job_ids: list[str] = []
        try:
            job = self._scheduler.get_job(self.JOB_ID)
            if job is not None and job.next_run_time is not None:
                next_run = job.next_run_time.isoformat()
            job_ids = [j.id for j in self._scheduler.get_jobs()]
        except Exception:  # noqa: BLE001
            next_run = None
        return {
            "enabled": allowed,
            "block_reason": block_reason,
            "running": bool(self._scheduler.running),
            "started": self._started,
            "tick_in_progress": self._tick_in_progress,
            "interval_seconds": interval,
            "job_id": self.JOB_ID,
            "job_ids": job_ids,
            "last_run_at": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "next_run_at": next_run,
            "last_duration_ms": self._last_duration_ms,
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
            "overlap_skip_count": self._overlap_skip_count,
            "run_count": self._run_count,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "last_result": self._last_result,
            "shadow_only": True,
            "live_order": False,
            "orders_created": 0,
        }

    async def run_once_now(self, *, notify: bool = True) -> dict[str, Any]:
        return await self._run_tick(notify=notify)

    async def _run_tick(self, *, notify: bool = True) -> dict[str, Any]:
        from stock_platform.operation.upbit_opportunity_shadow.evaluator import (
            UpbitOpportunityShadowEvaluator,
        )
        from stock_platform.operation.upbit_opportunity_shadow.mismatch import (
            ShadowEvaluationMismatchWatch,
        )

        if self._tick_in_progress:
            self._overlap_skip_count += 1
            return {
                "ok": False,
                "skipped": True,
                "code": "OVERLAP_SKIP",
                "orders_created": 0,
            }

        self._tick_in_progress = True
        self._last_run_at = datetime.now(timezone.utc)
        self._run_count += 1
        started = time.perf_counter()
        Session = get_session_factory()
        try:
            with Session() as session:
                try:
                    eval_out = await UpbitOpportunityShadowEvaluator(
                        session
                    ).evaluate_pending(notify=notify)
                    # COMPLETED 중 watch 미완료 건만 READ ONLY 비교
                    from sqlalchemy import select

                    from stock_platform.operation.upbit_opportunity_shadow.constants import (
                        SHADOW_STATUS_COMPLETED,
                    )
                    from stock_platform.operation.upbit_opportunity_shadow.entities import (
                        UpbitOpportunityShadowEntity,
                    )

                    completed_rows = list(
                        session.scalars(
                            select(UpbitOpportunityShadowEntity).where(
                                UpbitOpportunityShadowEntity.status
                                == SHADOW_STATUS_COMPLETED,
                                UpbitOpportunityShadowEntity.deleted_at.is_(
                                    None
                                ),
                            )
                        )
                    )
                    pending_watch = []
                    for row in completed_rows:
                        detail = row.evaluation_detail or {}
                        watch = detail.get("mismatch_watch") or {}
                        if watch.get("ok") is True and watch.get("code") == "MATCH":
                            continue
                        if watch.get("code") == "SHADOW_EVALUATION_MISMATCH":
                            continue  # 이미 경고됨 — 중복 알림 방지
                        pending_watch.append(row)
                    mismatch_out: dict[str, Any] = {
                        "checked": 0,
                        "mismatches": 0,
                    }
                    if pending_watch:
                        mismatch_out = await ShadowEvaluationMismatchWatch(
                            session
                        ).verify_many(pending_watch, notify=notify)

                    from stock_platform.operation.upbit_opportunity_shadow.cohort_milestone import (
                        ShadowCohortMilestoneWatch,
                    )

                    milestone_out = ShadowCohortMilestoneWatch(session).observe(
                        notify=notify
                    )

                    # B1 forward daily research summary — fail-open
                    b1_daily: dict[str, Any] = {"ok": True, "skipped": True}
                    try:
                        from stock_platform.operation.upbit_opportunity_shadow.entry_b1_daily_watch import (
                            EntryB1ForwardDailyWatch,
                        )

                        b1_daily = EntryB1ForwardDailyWatch(session).observe(
                            notify=notify
                        )
                    except Exception as exc:  # noqa: BLE001
                        b1_daily = {
                            "ok": False,
                            "research_failed_open": True,
                            "error": type(exc).__name__,
                        }

                    self._last_duration_ms = int(
                        (time.perf_counter() - started) * 1000
                    )
                    result = {
                        "ok": True,
                        "evaluated": eval_out.get("evaluated"),
                        "completed": eval_out.get("completed"),
                        "mismatch": mismatch_out,
                        "cohort_milestone": {
                            "status": milestone_out.get("status"),
                            "code": milestone_out.get("code"),
                            "notified": milestone_out.get("notified"),
                            "already_notified": milestone_out.get(
                                "already_notified"
                            ),
                            "snapshot": milestone_out.get("snapshot"),
                        },
                        "entry_b1_daily": {
                            "ok": b1_daily.get("ok"),
                            "skipped": b1_daily.get("skipped"),
                            "notified": b1_daily.get("notified"),
                            "day_kst": b1_daily.get("day_kst"),
                        },
                        "duration_ms": self._last_duration_ms,
                        "orders_created": 0,
                        "shadow_only": True,
                        "live_order": False,
                    }
                    self._last_result = result
                    self._last_success_at = datetime.now(timezone.utc)
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
                        "upbit_shadow_evaluator_tick_failed",
                        error=type(exc).__name__,
                    )
                    return {
                        "ok": False,
                        "error": type(exc).__name__,
                        "orders_created": 0,
                        "shadow_only": True,
                        "duration_ms": self._last_duration_ms,
                    }
        finally:
            self._tick_in_progress = False


upbit_opportunity_shadow_evaluator_scheduler = (
    UpbitOpportunityShadowEvaluatorScheduler()
)
