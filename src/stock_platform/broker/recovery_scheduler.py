"""STEP 8-5-3 — Broker Recovery APScheduler (lifecycle 통합)."""

from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from stock_platform.broker.recovery_scheduler_models import (
    BrokerRecoverySchedulerJobEntity,
)
from stock_platform.broker.recovery_scheduler_service import (
    BrokerRecoverySchedulerService,
    KNOWN_JOB_IDS,
    run_recovery_scheduler_job,
)
from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory


class BrokerRecoveryScheduler:
    """기존 lifecycle AsyncIOScheduler 패턴을 따르는 Recovery Job 등록기."""

    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )
        self._configured = False

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    def _parse_cron(self, expression: str, timezone: str) -> CronTrigger:
        parts = expression.strip().split()
        if len(parts) != 5:
            raise ValueError(
                f"Unsupported cron (need 5 fields): {expression}"
            )
        minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=timezone,
        )

    def _make_runner(self, job_id: str):
        async def _run() -> None:
            try:
                result = await run_recovery_scheduler_job(
                    job_id,
                    trigger_type="SCHEDULER",
                    requested_by=f"apscheduler:{job_id}",
                )
                logger.info(
                    "broker_recovery_scheduler_job_finished",
                    job_id=job_id,
                    status=result.get("status"),
                    account_count=result.get("account_count"),
                    success_count=result.get("success_count"),
                    failed_count=result.get("failed_count"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "broker_recovery_scheduler_job_failed",
                    job_id=job_id,
                    error_type=exc.__class__.__name__,
                    message=str(exc)[:500],
                )

        return _run

    def configure(self) -> None:
        """DB Job 설정을 읽어 APScheduler에 등록 (replace_existing)."""

        settings = get_settings()
        if not getattr(settings, "recovery_scheduler_enabled", True):
            logger.info("recovery_scheduler_disabled")
            return

        session = get_session_factory()()
        try:
            jobs = BrokerRecoverySchedulerService(session).list_jobs()
            if not jobs:
                logger.warning("recovery_scheduler_no_jobs_in_db")
                return

            for job in jobs:
                self._register_job(job)
                # next_run 추정 — Scheduler start 전에는 next_run_time 없을 수 있음
                aps_job = self._scheduler.get_job(job.job_id)
                if aps_job is None:
                    continue
                nxt = getattr(aps_job, "next_run_time", None)
                if nxt is None:
                    # pending Job: trigger에서 다음 시각 계산 시도
                    try:
                        trigger = getattr(aps_job, "trigger", None)
                        if trigger is not None:
                            nxt = trigger.get_next_fire_time(
                                None, datetime.now(timezone.utc)
                            )
                    except Exception:  # noqa: BLE001
                        nxt = None
                if nxt is not None:
                    if nxt.tzinfo is None:
                        nxt = nxt.replace(tzinfo=timezone.utc)
                    job.next_run_at = nxt.astimezone(timezone.utc)
            session.commit()
            self._configured = True
        finally:
            session.close()

    def _register_job(self, job: BrokerRecoverySchedulerJobEntity) -> None:
        if job.job_id not in KNOWN_JOB_IDS:
            logger.warning(
                "recovery_scheduler_unknown_job_skipped",
                job_id=job.job_id,
            )
            return

        trigger: CronTrigger | IntervalTrigger
        if job.trigger_type == "CRON":
            if not job.cron_expression:
                return
            trigger = self._parse_cron(
                job.cron_expression, job.timezone or "Asia/Seoul"
            )
        else:
            minutes = int(job.interval_minutes or 0)
            if minutes <= 0:
                return
            trigger = IntervalTrigger(
                minutes=minutes,
                timezone=job.timezone or "Asia/Seoul",
            )

        self._scheduler.add_job(
            self._make_runner(job.job_id),
            trigger=trigger,
            id=job.job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )

    def reload(self) -> None:
        """설정 변경 후 Job 재등록."""

        if not self._scheduler.running:
            self.configure()
            return
        # 기존 Recovery Job만 제거 후 재등록
        for job_id in KNOWN_JOB_IDS:
            existing = self._scheduler.get_job(job_id)
            if existing is not None:
                existing.remove()
        self.configure()

    def start(self) -> None:
        if self._scheduler.running:
            # reload 시 재구성만
            self.reload()
            return
        self.configure()
        if not self._scheduler.get_jobs():
            logger.info("recovery_scheduler_no_jobs_registered")
            return
        self._scheduler.start()
        logger.info(
            "recovery_scheduler_started",
            jobs=[j.id for j in self._scheduler.get_jobs()],
        )

    def status(self) -> dict:
        """Dashboard/Admin용 상태 — Desired와 별도로 Actual/Cooldown를 명시."""

        settings = get_settings()
        enabled = bool(
            getattr(settings, "recovery_scheduler_enabled", True)
        )
        running = bool(self._scheduler.running)
        jobs_out = []
        earliest_next = None
        for job in self._scheduler.get_jobs():
            nxt = job.next_run_time
            jobs_out.append(
                {
                    "job_id": job.id,
                    "next_run_at": (
                        nxt.isoformat() if nxt is not None else None
                    ),
                }
            )
            if nxt is not None and (
                earliest_next is None or nxt < earliest_next
            ):
                earliest_next = nxt

        cooldown_active = False
        cooldown_remaining_seconds: int | None = None
        reason_code: str | None = None
        try:
            from stock_platform.broker.recovery_runtime import (
                broker_recovery_manager,
            )

            cooldown_sec = int(
                getattr(
                    settings,
                    "recovery_scheduler_startup_cooldown_seconds",
                    120,
                )
            )
            finished = getattr(
                broker_recovery_manager, "_startup_finished_at", None
            )
            if (
                enabled
                and running
                and finished is not None
                and cooldown_sec > 0
            ):
                now = datetime.now(timezone.utc)
                finished_utc = (
                    finished
                    if finished.tzinfo is not None
                    else finished.replace(tzinfo=timezone.utc)
                )
                elapsed = (now - finished_utc).total_seconds()
                if elapsed < cooldown_sec:
                    cooldown_active = True
                    cooldown_remaining_seconds = max(
                        0, int(cooldown_sec - elapsed)
                    )
                    reason_code = "STARTUP_COOLDOWN"
        except Exception:  # noqa: BLE001
            pass

        if not enabled:
            actual_state = "DISABLED"
            reason_code = reason_code or "RECOVERY_SCHEDULER_DISABLED"
        elif cooldown_active:
            actual_state = "COOLDOWN"
        elif running:
            actual_state = "RUNNING"
        elif self._configured:
            actual_state = "STOPPED"
            reason_code = reason_code or "NOT_STARTED"
        else:
            actual_state = "STOPPED"
            reason_code = reason_code or "NOT_CONFIGURED"

        # DB Job 실행 이력 (민감정보 없음)
        last_success_at = None
        last_failed_at = None
        consecutive_failures = 0
        last_error_code = None
        try:
            session = get_session_factory()()
            try:
                rows = BrokerRecoverySchedulerService(session).list_jobs()
                fail_streak = 0
                for row in rows:
                    status_code = str(
                        getattr(row, "last_status", "") or ""
                    ).upper()
                    finished_at = getattr(row, "last_run_at", None)
                    if status_code in {"SUCCESS", "OK", "COMPLETED"}:
                        if last_success_at is None or (
                            finished_at
                            and (
                                last_success_at is None
                                or finished_at > last_success_at
                            )
                        ):
                            last_success_at = finished_at
                    elif status_code in {"FAILED", "ERROR", "TIMEOUT"}:
                        fail_streak += 1
                        if last_failed_at is None or (
                            finished_at
                            and (
                                last_failed_at is None
                                or finished_at > last_failed_at
                            )
                        ):
                            last_failed_at = finished_at
                            err = getattr(row, "last_error_summary", None)
                            last_error_code = (
                                str(err)[:80] if err else status_code
                            )
                consecutive_failures = fail_streak
            finally:
                session.close()
        except Exception:  # noqa: BLE001
            pass

        return {
            "running": running,
            "enabled": enabled,
            "configured": self._configured,
            "desired_state": "RUNNING" if enabled else "STOPPED",
            "actual_state": actual_state,
            "reason_code": reason_code,
            "cooldown_active": cooldown_active,
            "cooldown_remaining_seconds": cooldown_remaining_seconds,
            "apscheduler_jobs": jobs_out,
            "job_count": len(jobs_out),
            "timezone": str(self._scheduler.timezone),
            "next_run_at": (
                earliest_next.isoformat() if earliest_next else None
            ),
            "last_success_at": (
                last_success_at.isoformat()
                if last_success_at is not None
                else None
            ),
            "last_failed_at": (
                last_failed_at.isoformat()
                if last_failed_at is not None
                else None
            ),
            "consecutive_failures": consecutive_failures,
            "last_error_code": last_error_code,
            "stale": False,
        }

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)


broker_recovery_scheduler = BrokerRecoveryScheduler()
