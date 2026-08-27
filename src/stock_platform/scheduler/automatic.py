from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from stock_platform.common.settings import Settings, get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.scheduler.service import SchedulerService


logger = structlog.get_logger(__name__)

# STEP 8-5-13 — SESSION_DEPENDENT vs DATE_DEPENDENT/TIME_OF_DAY_ONLY Job 분류.
#
# ``portfolio_equity_snapshot_daily`` / ``ai_orchestration_daily`` 는 KRX
# 정규장 종료 시각에 종속된 SESSION_DEPENDENT Job이다. 지연개장·조기종료
# 등 특별 거래일에는 실제 종료 시각이 15:30이 아니므로, Calendar가 변경될
# 때 ``calendar_scheduler_recompute.recompute_krx_session_jobs``가 등록하는
# 동적 SNAPSHOT/AI_ANALYSIS Job(Timeline의 ``snapshot_at``/``analysis_at``
# 기준 1회성 실행)이 **Primary**로 동작한다. 이 모듈의 15:40/16:30 고정
# Cron은 동적 Job이 미등록·미기동(Scheduler 재기동, 등록 실패 등)인 경우의
# **Fallback Safety Net**이며, ``_krx_session_cron_gate``가 실제 Timeline과
# 비교해 너무 이르거나(SKIPPED_TOO_EARLY), 이미 늦었거나(SKIPPED_TOO_LATE),
# 이미 그날 실행됐으면(SKIPPED_ALREADY_EXECUTED) 중복 실행을 막는다.
#
# ``candidate_screening_daily`` / ``position_planning_daily`` 는 특정 장
# 이벤트 시각이 아니라 "매 평일 16:10/17:00"처럼 TIME_OF_DAY_ONLY 정책이라
# Session Timeline 게이트를 적용하지 않는다 (day_of_week=mon-fri 조건만
# 유지 — DATE_DEPENDENT 수준).
SESSION_DEPENDENT_JOB_NAMES: frozenset[str] = frozenset(
    {"portfolio_equity_snapshot", "ai_orchestration"}
)


class AutomaticScheduler:
    """장후 자동 작업을 실행하는 APScheduler 래퍼.

    API lifecycle과 분리되어 `scripts/run_scheduler.py` 워커로 기동한다.
    """

    # 테스트·문서·운영 계약의 단일 소스 (개수 하드코딩 금지)
    REGISTERED_JOB_IDS: frozenset[str] = frozenset(
        {
            "candidate_screening_daily",
            "ai_orchestration_daily",
            "position_planning_daily",
            "portfolio_equity_snapshot_daily",
            "upbit_krw_daily_sync_daily",
            "kiwoom_krx_daily_sync_daily",
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
        self._configured = False

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    def registered_job_ids(self) -> set[str]:
        return {
            job.id
            for job in self._scheduler.get_jobs()
        }

    def configure(self) -> None:
        self._scheduler.add_job(
            self._run_candidate_screening,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=self._settings.scheduler_candidate_hour,
                minute=self._settings.scheduler_candidate_minute,
                timezone=self._settings.scheduler_timezone,
            ),
            id="candidate_screening_daily",
            name="Candidate screening daily",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )

        self._scheduler.add_job(
            self._run_ai_orchestration,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=self._settings.scheduler_ai_hour,
                minute=self._settings.scheduler_ai_minute,
                timezone=self._settings.scheduler_timezone,
            ),
            id="ai_orchestration_daily",
            name="AI orchestration daily",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )

        self._scheduler.add_job(
            self._run_position_planning,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=self._settings.scheduler_position_hour,
                minute=self._settings.scheduler_position_minute,
                timezone=self._settings.scheduler_timezone,
            ),
            id="position_planning_daily",
            name="Position planning daily",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )

        self._scheduler.add_job(
            self._run_portfolio_equity_snapshot,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=self._settings.scheduler_equity_snapshot_hour,
                minute=(
                    self._settings.scheduler_equity_snapshot_minute
                ),
                timezone=self._settings.scheduler_timezone,
            ),
            id="portfolio_equity_snapshot_daily",
            name="Portfolio equity snapshot daily",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )

        self._scheduler.add_job(
            self._run_upbit_krw_daily_sync,
            trigger=CronTrigger(
                hour=self._settings.scheduler_upbit_daily_hour,
                minute=self._settings.scheduler_upbit_daily_minute,
                timezone=self._settings.scheduler_timezone,
            ),
            id="upbit_krw_daily_sync_daily",
            name="Upbit KRW daily sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        self._scheduler.add_job(
            self._run_kiwoom_krx_daily_sync,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=self._settings.scheduler_kiwoom_daily_hour,
                minute=self._settings.scheduler_kiwoom_daily_minute,
                timezone=self._settings.scheduler_timezone,
            ),
            id="kiwoom_krx_daily_sync_daily",
            name="Kiwoom KRX daily sync",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        self._configured = True

    def start(self) -> None:
        if not self._settings.scheduler_enabled:
            logger.info("automatic_scheduler_disabled")
            return

        # 중복 start 방지
        if self._scheduler.running:
            return

        self.configure()
        self._scheduler.start()

        logger.info(
            "automatic_scheduler_started",
            timezone=self._settings.scheduler_timezone,
            jobs=[
                job.id
                for job in self._scheduler.get_jobs()
            ],
        )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)

    async def run_job_now(
        self,
        job_name: str,
    ) -> dict[str, Any]:
        # ADMIN 수동 즉시실행은 Session Timeline Cron Fallback 게이트를
        # 건너뛴다(force=True) — 관리자가 명시적으로 요청한 실행이므로
        # SKIPPED_TOO_EARLY/TOO_LATE 등으로 막을 필요가 없다.
        mapping = {
            "candidate_screening": (
                self._run_candidate_screening
            ),
            "ai_orchestration": (
                lambda: self._run_ai_orchestration(force=True)
            ),
            "position_planning": (
                self._run_position_planning
            ),
            "portfolio_equity_snapshot": (
                lambda: self._run_portfolio_equity_snapshot(force=True)
            ),
            "upbit_krw_daily_sync": self._run_upbit_krw_daily_sync,
            "kiwoom_krx_daily_sync": self._run_kiwoom_krx_daily_sync,
        }

        try:
            handler = mapping[job_name]
        except KeyError as exc:
            raise LookupError(
                f"Automatic job not found: {job_name}"
            ) from exc

        return await handler()

    async def _krx_session_cron_gate(
        self,
        *,
        job_name: str,
        timeline_field: str,
    ) -> dict[str, Any] | None:
        """STEP 8-5-13 — Snapshot/AI 고정 Cron 실행 전 Timeline Fallback 게이트.

        ``None``을 반환하면 정상 진행(고정 Cron이 실제 실행 담당)한다.
        동적 SNAPSHOT/AI_ANALYSIS Job이 이미 정시에 실행했다면 이 고정
        Cron은 중복 실행을 피하고 스킵 사유만 기록한다.
        """

        settings = self._settings
        if str(settings.scheduler_exchange_code).upper() != "KRX":
            return None
        if not bool(getattr(settings, "krx_cron_fallback_enabled", True)):
            return None

        try:
            from stock_platform.operation.session_timeline import (
                resolve_krx_timeline,
            )

            timeline = resolve_krx_timeline()
        except Exception:  # noqa: BLE001
            # Timeline 계산 실패 — 기존 Calendar 게이트가 없는 잡이므로
            # Fail Closed 대신 고정 Cron을 그대로 실행되게 둔다.
            return None

        if not timeline.is_trading_day or not timeline.live_allowed:
            from stock_platform.operation.calendar_constants import (
                CALENDAR_UNAVAILABLE_REASONS,
            )

            skip_status = (
                "SKIPPED_CALENDAR_UNAVAILABLE"
                if timeline.reason_code in CALENDAR_UNAVAILABLE_REASONS
                else "SKIPPED_NON_TRADING_DAY"
            )
            return {
                "status": skip_status,
                "job_name": job_name,
                "reason_code": timeline.reason_code,
            }

        target = getattr(timeline, timeline_field, None)
        if target is None:
            return None

        now = datetime.now(target.tzinfo)
        early_tol = int(
            getattr(
                settings, "krx_cron_fallback_early_tolerance_minutes", 5
            )
        )
        late_tol = int(
            getattr(
                settings, "krx_cron_fallback_late_tolerance_minutes", 60
            )
        )

        from stock_platform.operation.session_timeline import (
            krx_cron_fallback_timing,
        )

        timing = krx_cron_fallback_timing(
            now=now,
            target_at=target,
            early_tolerance_minutes=early_tol,
            late_tolerance_minutes=late_tol,
        )
        if timing == "TOO_EARLY":
            return {
                "status": "SKIPPED_TOO_EARLY",
                "job_name": job_name,
                "target_at": target.isoformat(),
                "now": now.isoformat(),
                "revision": timeline.revision,
            }
        if timing == "TOO_LATE":
            return {
                "status": "SKIPPED_TOO_LATE",
                "job_name": job_name,
                "target_at": target.isoformat(),
                "now": now.isoformat(),
                "revision": timeline.revision,
            }

        # 이미 오늘 목표 시각 이후 성공 실행된 이력이 있으면 중복 실행 방지
        # (동적 SNAPSHOT/AI_ANALYSIS Job 또는 직전 고정 Cron 실행분 포함)
        session = get_session_factory()()
        try:
            from stock_platform.operation.job_repository import (
                JobRunRepository,
            )

            recent = JobRunRepository(session).list_recent(
                job_name=job_name, status_code="SUCCESS", limit=1
            )
            if recent:
                last_started = recent[0].started_at
                if last_started is not None:
                    last_local = (
                        last_started.astimezone(target.tzinfo)
                        if last_started.tzinfo
                        else last_started.replace(tzinfo=target.tzinfo)
                    )
                    if (
                        last_local.date() == target.date()
                        and last_local >= target - timedelta(minutes=early_tol)
                    ):
                        return {
                            "status": "SKIPPED_ALREADY_EXECUTED",
                            "job_name": job_name,
                            "target_at": target.isoformat(),
                            "last_run_at": last_local.isoformat(),
                            "revision": timeline.revision,
                        }
        except Exception:  # noqa: BLE001
            pass
        finally:
            session.close()

        # STEP 8-5-15 — market_session_job_enabled면 이 고정 Cron은 더 이상
        # Snapshot/AI를 직접 실행하지 않는다. DB Job 존재/기상만 보장하고
        # 실제 실행은 Dispatcher(Poller)가 담당한다.
        if bool(
            getattr(settings, "market_session_job_enabled", True)
        ) and bool(
            getattr(settings, "market_session_cron_wakeup_enabled", True)
        ):
            job_type_map = {
                "portfolio_equity_snapshot": "KRX_EQUITY_SNAPSHOT",
                "ai_orchestration": "KRX_AI_ANALYSIS",
            }
            job_type = job_type_map.get(job_name)
            if job_type is not None:
                wakeup_session = get_session_factory()()
                try:
                    from stock_platform.operation.market_session_job_service import (
                        MarketSessionJobService,
                    )

                    wakeup = MarketSessionJobService(
                        wakeup_session
                    ).ensure_wakeup(
                        exchange_code="KRX",
                        job_type=job_type,
                        market_date=target.date(),
                    )
                    return {
                        "status": "DELEGATED_TO_MARKET_SESSION_JOB",
                        "job_name": job_name,
                        "target_at": target.isoformat(),
                        "now": now.isoformat(),
                        "revision": timeline.revision,
                        "wakeup": wakeup,
                    }
                except Exception as exc:  # noqa: BLE001
                    # 위임 실패 시 레거시 직접 실행으로 Fail Open
                    logger.warning(
                        "market_session_job_wakeup_delegate_failed",
                        job_name=job_name,
                        error=str(exc)[:300],
                    )
                finally:
                    wakeup_session.close()
        return None

    async def _execute_registered_job(
        self,
        *,
        job_name: str,
        payload: dict[str, Any],
        gate_timeline_field: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        if (
            not force
            and gate_timeline_field is not None
            and job_name in SESSION_DEPENDENT_JOB_NAMES
        ):
            skip = await self._krx_session_cron_gate(
                job_name=job_name, timeline_field=gate_timeline_field
            )
            if skip is not None:
                logger.info(
                    "automatic_job_skipped_krx_cron_fallback",
                    **skip,
                )
                return skip

        session = get_session_factory()()

        try:
            history, result = await SchedulerService(
                session
            ).execute(
                job_name=job_name,
                payload=payload,
                trigger_type="SCHEDULED",
            )

            logger.info(
                "automatic_job_completed",
                job_name=job_name,
                job_run_id=history.job_run_id,
                status_code=history.status_code,
            )

            return {
                "job_run_id": history.job_run_id,
                "status_code": history.status_code,
                "result": result,
            }
        except Exception:
            logger.exception(
                "automatic_job_failed",
                job_name=job_name,
            )
            raise
        finally:
            session.close()

    async def _run_candidate_screening(
        self,
    ) -> dict[str, Any]:
        return await self._execute_registered_job(
            job_name="candidate_screening",
            payload={
                "exchange_code": (
                    self._settings.scheduler_exchange_code
                ),
                "as_of_date": date.today().isoformat(),
                "limit": (
                    self._settings.scheduler_candidate_limit
                ),
                "minimum_score": (
                    self._settings.scheduler_minimum_score
                ),
                "require_all_rules": False,
                "run_type": "DAILY",
            },
        )

    async def _run_ai_orchestration(
        self,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        return await self._execute_registered_job(
            job_name="ai_orchestration",
            gate_timeline_field="analysis_at",
            force=force,
            payload={
                "exchange_code": (
                    self._settings.scheduler_exchange_code
                ),
                "limit": self._settings.scheduler_ai_limit,
                "news_limit": 20,
                "disclosure_limit": 20,
                "lookback_days": 90,
                "minimum_ai_score": (
                    self._settings.scheduler_minimum_ai_score
                ),
                "minimum_confidence": (
                    self._settings.scheduler_minimum_confidence
                ),
            },
        )

    async def _run_position_planning(
        self,
    ) -> dict[str, Any]:
        return await self._execute_registered_job(
            job_name="position_planning",
            payload={
                "exchange_code": (
                    self._settings.scheduler_exchange_code
                ),
                "policy_id": (
                    self._settings.scheduler_policy_id
                ),
                "portfolio_value": (
                    self._settings.scheduler_portfolio_value
                ),
                "available_cash": (
                    self._settings.scheduler_available_cash
                ),
                "current_position_count": 0,
                "limit": (
                    self._settings.scheduler_position_limit
                ),
                "minimum_ai_score": (
                    self._settings.scheduler_minimum_ai_score
                ),
                "minimum_confidence": (
                    self._settings
                    .scheduler_minimum_confidence
                ),
                "allowed_actions": [
                    "WATCH",
                    "REVIEW",
                ],
            },
        )

    async def _run_portfolio_equity_snapshot(
        self,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        return await self._execute_registered_job(
            job_name="portfolio_equity_snapshot",
            gate_timeline_field="snapshot_at",
            force=force,
            payload={
                "snapshot_date": date.today().isoformat(),
                "include_live": True,
            },
        )

    async def _run_upbit_krw_daily_sync(
        self,
    ) -> dict[str, Any]:
        return await self._execute_registered_job(
            job_name="upbit_krw_daily_sync",
            payload={
                "resume": True,
                "lookback_years": 1,
                "sync_instruments": True,
            },
        )

    async def _run_kiwoom_krx_daily_sync(
        self,
    ) -> dict[str, Any]:
        from stock_platform.operation.calendar_repository import (
            TradingCalendarRepository,
        )
        from stock_platform.operation.calendar_service import (
            TradingCalendarService,
        )

        session = get_session_factory()()
        try:
            if not TradingCalendarService(
                TradingCalendarRepository(session)
            ).is_trading_day("KRX", date.today()):
                return {
                    "status": "SKIPPED_NON_TRADING_DAY",
                    "job_name": "kiwoom_krx_daily_sync",
                }
        finally:
            session.close()

        return await self._execute_registered_job(
            job_name="kiwoom_krx_daily_sync",
            payload={
                "resume": True,
                "lookback_days": 30,
            },
        )


async def run_forever() -> None:
    scheduler = AutomaticScheduler()
    scheduler.start()

    stop_event = asyncio.Event()

    try:
        await stop_event.wait()
    finally:
        await scheduler.shutdown()
