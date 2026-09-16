"""KRX Realtime 세션 스케줄러 — STEP 8-5-13 Calendar Timeline 연동.

고정 Cron(08:50/09:00/15:20/15:40)은 Fallback Safety Net으로 유지한다.
실제 전환 시각은 Session Timeline(개장·Cutoff·마감·Post-close)을 따른다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import (
    AsyncIOScheduler,
)
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from stock_platform.common.settings import (
    Settings,
    get_settings,
)
from stock_platform.database.session import (
    get_session_factory,
)
from stock_platform.realtime.session_models import (
    TradingSessionPhase,
)
from stock_platform.realtime.session_service import (
    RealtimeTradingSessionService,
)

logger = logging.getLogger(__name__)

# Calendar Phase → Realtime 세션 Phase 매핑
# EXIT_ONLY는 Runner를 유지하고 주문 Guard만 제한한다.
_LAST_APPLIED_CALENDAR_PHASE: str | None = None
_LAST_APPLIED_REVISION: int | None = None


class RealtimeTradingScheduler:
    """KRX 자동매매 세션 시간을 APScheduler로 관리한다."""

    REGISTERED_JOB_IDS: frozenset[str] = frozenset(
        {
            "realtime_pre_market",
            "realtime_market_open",
            "realtime_market_close",
            "realtime_after_market",
        }
    )

    def __init__(
        self,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=self._settings.scheduler_timezone
        )

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    def registered_job_ids(self) -> set[str]:
        return {
            job.id
            for job in self._scheduler.get_jobs()
            if job.id in self.REGISTERED_JOB_IDS
        }

    def configure(self) -> None:
        """고정 Cron Fallback 등록 (실제 실행은 Timeline 게이트)."""

        # 기본 시각은 정규장 기준 Fallback — 실행 직전 Timeline 검증
        self._add_cron_job(
            job_id="realtime_pre_market",
            phase=TradingSessionPhase.PRE_MARKET,
            hour=8,
            minute=50,
            timeline_field="preopen_start_at",
        )
        self._add_cron_job(
            job_id="realtime_market_open",
            phase=TradingSessionPhase.MARKET_OPEN,
            hour=9,
            minute=0,
            timeline_field="regular_open_at",
        )
        # 15:20 Fallback = 신규 진입 Cutoff(EXIT_ONLY). Runner는 유지.
        self._add_cron_job(
            job_id="realtime_market_close",
            phase=TradingSessionPhase.MARKET_CLOSE,
            hour=15,
            minute=20,
            timeline_field="regular_close_at",
        )
        self._add_cron_job(
            job_id="realtime_after_market",
            phase=TradingSessionPhase.AFTER_MARKET,
            hour=15,
            minute=40,
            timeline_field="post_close_start_at",
        )

    def start(self) -> None:
        if self._scheduler.running:
            return

        self.configure()
        self._scheduler.start()
        try:
            from stock_platform.trading.trading_scheduler_control import (
                record_trading_scheduler_tick,
            )

            record_trading_scheduler_tick()
        except Exception:  # noqa: BLE001
            pass
        # 서버 중간 기동 시 현재 Calendar Phase로 즉시 동기화 +
        # 오늘 Timeline DateTrigger 등록 (고정 Cron은 Fallback)
        try:
            self._scheduler.add_job(
                self.sync_current_phase_from_timeline,
                trigger="date",
                run_date=datetime.now(
                    self._scheduler.timezone
                )
                + timedelta(seconds=2),
                id="realtime_timeline_bootstrap",
                replace_existing=True,
            )
            # 5분마다 Phase 재평가 (Revision 변경·중간 기동 대응)
            self._scheduler.add_job(
                self.sync_current_phase_from_timeline,
                trigger=CronTrigger(
                    minute="*/5",
                    timezone=self._settings.scheduler_timezone,
                ),
                id="realtime_timeline_resync",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            # STEP 9-5 No-Order 관찰용 — 짧은 heartbeat (주문 경로 없음)
            self._scheduler.add_job(
                self._heartbeat_tick,
                trigger=CronTrigger(
                    second="*/10",
                    timezone=self._settings.scheduler_timezone,
                ),
                id="realtime_scheduler_heartbeat",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception("realtime_timeline_bootstrap_failed")

    def _heartbeat_tick(self) -> dict[str, Any]:
        """Scheduler 생존 신호 — 전략/주문 미실행."""
        try:
            from stock_platform.trading.trading_scheduler_control import (
                record_trading_scheduler_tick,
            )

            record_trading_scheduler_tick()
        except Exception:  # noqa: BLE001
            pass
        return {
            "status": "HEARTBEAT",
            "running": bool(self._scheduler.running),
            "order_path": False,
        }

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)

    async def run_phase_now(
        self,
        phase: TradingSessionPhase,
        *,
        timeline_field: str | None = None,
        force: bool = False,
    ):
        # Cron Fallback — Timeline 목표 시각과 어긋나면 Skip
        if not force and timeline_field:
            gate = self._timeline_cron_gate(timeline_field)
            if gate is not None:
                logger.info(
                    "realtime_session_cron_skipped",
                    extra=gate,
                )
                return {
                    "executed": False,
                    "message": gate.get("status"),
                    **gate,
                }

        session = get_session_factory()()
        try:
            result = await RealtimeTradingSessionService(
                session
            ).execute(
                phase=phase,
                exchange_code="KRX",
            )
            self._audit_phase_change(phase.value)
            return result
        finally:
            session.close()

    async def sync_current_phase_from_timeline(self) -> dict[str, Any]:
        """현재 시각의 Calendar Phase에 맞춰 Realtime 상태를 맞춘다."""

        global _LAST_APPLIED_CALENDAR_PHASE, _LAST_APPLIED_REVISION

        try:
            from stock_platform.operation.session_timeline import (
                TradingSessionPhase as CalPhase,
                resolve_krx_timeline,
            )

            timeline = resolve_krx_timeline()
            now = datetime.now(
                timeline.regular_open_at.tzinfo
                if timeline.regular_open_at
                else None
            )
            cal_phase = timeline.phase_at(now)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "realtime_timeline_sync_failed",
                extra={"error": str(exc)[:200]},
            )
            return {"status": "CALENDAR_UNAVAILABLE", "error": str(exc)[:200]}

        # Revision 변경 시 동적 Date Job 재등록
        if (
            _LAST_APPLIED_REVISION is not None
            and int(timeline.revision) != int(_LAST_APPLIED_REVISION)
        ):
            self._register_dynamic_timeline_jobs(timeline)

        _LAST_APPLIED_REVISION = int(timeline.revision)

        # Phase가 같으면 DateTrigger만 갱신하고 Runner 재실행 방지
        if _LAST_APPLIED_CALENDAR_PHASE == cal_phase.value:
            self._register_dynamic_timeline_jobs(timeline)
            return {
                "status": "UNCHANGED",
                "calendar_phase": cal_phase.value,
                "revision": timeline.revision,
            }

        # Calendar Phase → Realtime 동작 (전환 시에만)
        if cal_phase == CalPhase.NON_TRADING_DAY:
            self._audit_phase_change(cal_phase.value, revision=timeline.revision)
            return {"status": "NON_TRADING_DAY", "phase": cal_phase.value}

        if cal_phase == CalPhase.CALENDAR_UNAVAILABLE:
            self._audit_phase_change(cal_phase.value, revision=timeline.revision)
            return {
                "status": "CALENDAR_UNAVAILABLE",
                "phase": cal_phase.value,
                "health": "DEGRADED",
            }

        if cal_phase in {CalPhase.PREOPEN}:
            result = await self.run_phase_now(
                TradingSessionPhase.PRE_MARKET, force=True
            )
        elif cal_phase in {CalPhase.OPEN, CalPhase.EXIT_ONLY}:
            # EXIT_ONLY도 Runner 유지 (주문은 Safety Guard가 제한)
            result = await self.run_phase_now(
                TradingSessionPhase.MARKET_OPEN, force=True
            )
        elif cal_phase == CalPhase.CLOSED:
            result = await self.run_phase_now(
                TradingSessionPhase.MARKET_CLOSE, force=True
            )
        elif cal_phase == CalPhase.POST_CLOSE:
            result = await self.run_phase_now(
                TradingSessionPhase.AFTER_MARKET, force=True
            )
        else:
            result = {"status": "NOOP", "phase": cal_phase.value}

        self._audit_phase_change(cal_phase.value, revision=timeline.revision)
        self._register_dynamic_timeline_jobs(timeline)
        return {
            "status": "SYNCED",
            "calendar_phase": cal_phase.value,
            "revision": timeline.revision,
            "result": getattr(result, "__dict__", result),
        }

    def _register_dynamic_timeline_jobs(self, timeline: Any) -> None:
        """오늘 Timeline 기준 DateTrigger 등록 (주 실행 경로)."""

        if not bool(
            getattr(self._settings, "krx_dynamic_session_jobs_enabled", True)
        ):
            return

        plans = [
            (
                "realtime_dyn_preopen",
                timeline.preopen_start_at,
                TradingSessionPhase.PRE_MARKET,
            ),
            (
                "realtime_dyn_open",
                timeline.regular_open_at,
                TradingSessionPhase.MARKET_OPEN,
            ),
            (
                "realtime_dyn_close",
                timeline.regular_close_at,
                TradingSessionPhase.MARKET_CLOSE,
            ),
            (
                "realtime_dyn_postclose",
                timeline.post_close_start_at,
                TradingSessionPhase.AFTER_MARKET,
            ),
        ]
        now = datetime.now(
            timeline.regular_open_at.tzinfo
            if timeline.regular_open_at
            else None
        )
        for job_id, run_at, phase in plans:
            if run_at is None:
                continue
            try:
                self._scheduler.remove_job(job_id)
            except Exception:  # noqa: BLE001
                pass
            if run_at <= now:
                continue
            try:
                self._scheduler.add_job(
                    self.run_phase_now,
                    trigger=DateTrigger(run_date=run_at),
                    kwargs={"phase": phase, "force": True},
                    id=job_id,
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=1800,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "realtime_dynamic_job_register_failed",
                    extra={"job_id": job_id},
                )

    def _timeline_cron_gate(self, timeline_field: str) -> dict[str, Any] | None:
        if not bool(
            getattr(self._settings, "krx_cron_fallback_enabled", True)
        ):
            return None
        try:
            from stock_platform.operation.session_timeline import (
                krx_cron_fallback_timing,
                resolve_krx_timeline,
            )

            timeline = resolve_krx_timeline()
            target = getattr(timeline, timeline_field, None)
            if target is None:
                return None
            now = datetime.now(target.tzinfo)
            early = int(
                getattr(
                    self._settings,
                    "krx_cron_fallback_early_tolerance_minutes",
                    5,
                )
            )
            late = int(
                getattr(
                    self._settings,
                    "krx_cron_fallback_late_tolerance_minutes",
                    60,
                )
            )
            timing = krx_cron_fallback_timing(
                now=now,
                target_at=target,
                early_tolerance_minutes=early,
                late_tolerance_minutes=late,
            )
            if timing == "TOO_EARLY":
                return {
                    "status": "SKIPPED_TOO_EARLY",
                    "timeline_field": timeline_field,
                    "target_at": target.isoformat(),
                    "revision": timeline.revision,
                }
            if timing == "TOO_LATE":
                return {
                    "status": "SKIPPED_TOO_LATE",
                    "timeline_field": timeline_field,
                    "target_at": target.isoformat(),
                    "revision": timeline.revision,
                }
        except Exception:  # noqa: BLE001
            return None
        return None

    def _audit_phase_change(
        self, phase_value: str, *, revision: int | None = None
    ) -> None:
        global _LAST_APPLIED_CALENDAR_PHASE
        if _LAST_APPLIED_CALENDAR_PHASE == phase_value:
            return
        previous = _LAST_APPLIED_CALENDAR_PHASE
        _LAST_APPLIED_CALENDAR_PHASE = phase_value
        try:
            from stock_platform.operation.calendar_audit import (
                audit_calendar_event,
            )

            audit_calendar_event(
                "SESSION_PHASE_CHANGED",
                detail={
                    "from_phase": previous,
                    "to_phase": phase_value,
                    "revision": revision,
                },
            )
        except Exception:  # noqa: BLE001
            pass

    def _add_cron_job(
        self,
        *,
        job_id: str,
        phase: TradingSessionPhase,
        hour: int,
        minute: int,
        timeline_field: str,
    ) -> None:
        self._scheduler.add_job(
            self.run_phase_now,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=hour,
                minute=minute,
                timezone=(
                    self._settings.scheduler_timezone
                ),
            ),
            kwargs={
                "phase": phase,
                "timeline_field": timeline_field,
            },
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )
