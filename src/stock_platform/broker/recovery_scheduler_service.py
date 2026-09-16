"""STEP 8-5-3 — Recovery Scheduler Job 설정·검증·실행 오케스트레이션."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultService,
)
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_scheduler_models import (
    BrokerRecoverySchedulerJobEntity,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.calendar_repository import (
    TradingCalendarRepository,
)
from stock_platform.operation.calendar_service import TradingCalendarService
from stock_platform.operation.job_repository import JobRunRepository
from stock_platform.operation.job_service import JobExecutionService

logger = structlog.get_logger(__name__)


# Credential/정책상 자동 재시도 금지
NON_RETRYABLE_ERROR_CODES = frozenset(
    {
        "credential_missing",
        "credential_invalid",
        "credential_decryption_failed",
        "credential_expired",
        "credential_broker_mismatch",
        "credential_unverified",
        "vault_unavailable",
        "manual_review_required",
        "account_inactive",
        "account_paused",
    }
)

KNOWN_JOB_IDS = (
    "broker_recovery_kiwoom_preopen",
    "broker_recovery_kiwoom_postclose",
    "broker_recovery_upbit_interval",
    "broker_recovery_paper_integrity",
    "broker_recovery_failed_retry",
)

# Interval 최소값 (분) — 폭주 방지
MIN_INTERVAL_BY_JOB = {
    "broker_recovery_upbit_interval": 10,
    "broker_recovery_paper_integrity": 60,
    "broker_recovery_failed_retry": 5,
}


class RecoverySchedulerConfigError(ValueError):
    """잘못된 Job 설정."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_job_update(payload: dict[str, Any]) -> dict[str, Any]:
    """ADMIN 설정 변경 Validation."""

    cleaned: dict[str, Any] = {}
    if "is_enabled" in payload:
        cleaned["is_enabled"] = bool(payload["is_enabled"])
    if "cron_expression" in payload:
        cron = payload["cron_expression"]
        if cron is not None:
            cron = str(cron).strip()
            parts = cron.split()
            if len(parts) not in {5, 6}:
                raise RecoverySchedulerConfigError(
                    "cron_expression must have 5 fields "
                    "(min hour dom mon dow)"
                )
            cleaned["cron_expression"] = cron
    if "interval_minutes" in payload:
        minutes = payload["interval_minutes"]
        if minutes is not None:
            minutes = int(minutes)
            if minutes <= 0:
                raise RecoverySchedulerConfigError(
                    "interval_minutes must be positive"
                )
            cleaned["interval_minutes"] = minutes
    if "timeout_seconds" in payload:
        timeout = int(payload["timeout_seconds"])
        if timeout <= 0:
            raise RecoverySchedulerConfigError(
                "timeout_seconds must be positive"
            )
        if timeout > 3600:
            raise RecoverySchedulerConfigError(
                "timeout_seconds max is 3600"
            )
        cleaned["timeout_seconds"] = timeout
    if "max_retries" in payload:
        retries = int(payload["max_retries"])
        if retries < 0:
            raise RecoverySchedulerConfigError(
                "max_retries must be >= 0"
            )
        if retries > 20:
            raise RecoverySchedulerConfigError(
                "max_retries max is 20"
            )
        cleaned["max_retries"] = retries
    if "concurrency" in payload:
        conc = int(payload["concurrency"])
        if conc < 1 or conc > 10:
            raise RecoverySchedulerConfigError(
                "concurrency must be 1..10"
            )
        cleaned["concurrency"] = conc
    if "backoff_base_seconds" in payload:
        base = int(payload["backoff_base_seconds"])
        if base < 1:
            raise RecoverySchedulerConfigError(
                "backoff_base_seconds must be >= 1"
            )
        cleaned["backoff_base_seconds"] = base
    if "backoff_max_seconds" in payload:
        mx = int(payload["backoff_max_seconds"])
        if mx < 1:
            raise RecoverySchedulerConfigError(
                "backoff_max_seconds must be >= 1"
            )
        cleaned["backoff_max_seconds"] = mx
    return cleaned


def job_entity_as_dict(
    row: BrokerRecoverySchedulerJobEntity,
) -> dict[str, Any]:
    return {
        "job_id": row.job_id,
        "display_name": row.display_name,
        "broker_code": row.broker_code,
        "trigger_type": row.trigger_type,
        "is_enabled": bool(row.is_enabled),
        "cron_expression": row.cron_expression,
        "interval_minutes": row.interval_minutes,
        "timezone": row.timezone,
        "timeout_seconds": int(row.timeout_seconds),
        "max_retries": int(row.max_retries),
        "backoff_base_seconds": int(row.backoff_base_seconds),
        "backoff_max_seconds": int(row.backoff_max_seconds),
        "concurrency": int(row.concurrency),
        "last_run_at": (
            row.last_run_at.isoformat() if row.last_run_at else None
        ),
        "next_run_at": (
            row.next_run_at.isoformat() if row.next_run_at else None
        ),
        "last_status": row.last_status,
        "last_error_summary": row.last_error_summary,
        "last_result_summary": dict(row.last_result_summary or {}),
        "updated_by": row.updated_by,
        "updated_at": (
            row.updated_at.isoformat() if row.updated_at else None
        ),
    }


class BrokerRecoverySchedulerService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_jobs(self) -> list[BrokerRecoverySchedulerJobEntity]:
        stmt = select(BrokerRecoverySchedulerJobEntity).order_by(
            BrokerRecoverySchedulerJobEntity.job_id
        )
        return list(self._session.scalars(stmt))

    def get_job(
        self, job_id: str
    ) -> BrokerRecoverySchedulerJobEntity | None:
        stmt = select(BrokerRecoverySchedulerJobEntity).where(
            BrokerRecoverySchedulerJobEntity.job_id == job_id
        )
        return self._session.scalar(stmt.limit(1))

    def require_job(
        self, job_id: str
    ) -> BrokerRecoverySchedulerJobEntity:
        row = self.get_job(job_id)
        if row is None:
            raise LookupError(f"Unknown recovery scheduler job: {job_id}")
        return row

    def update_job(
        self,
        job_id: str,
        payload: dict[str, Any],
        *,
        actor: str,
    ) -> BrokerRecoverySchedulerJobEntity:
        row = self.require_job(job_id)
        cleaned = validate_job_update(payload)

        # Interval 하한 (Job별)
        if "interval_minutes" in cleaned:
            minimum = MIN_INTERVAL_BY_JOB.get(job_id, 5)
            if cleaned["interval_minutes"] < minimum:
                raise RecoverySchedulerConfigError(
                    f"interval_minutes minimum for {job_id} is {minimum}"
                )
            if row.trigger_type != "INTERVAL":
                raise RecoverySchedulerConfigError(
                    "interval_minutes only valid for INTERVAL jobs"
                )

        if "cron_expression" in cleaned and row.trigger_type != "CRON":
            raise RecoverySchedulerConfigError(
                "cron_expression only valid for CRON jobs"
            )

        for key, value in cleaned.items():
            setattr(row, key, value)
        row.updated_by = actor
        row.updated_at = _utcnow()
        self._session.flush()
        return row

    def set_enabled(
        self, job_id: str, *, enabled: bool, actor: str
    ) -> BrokerRecoverySchedulerJobEntity:
        return self.update_job(
            job_id, {"is_enabled": enabled}, actor=actor
        )


def is_krx_trading_day(session: Session, day=None) -> tuple[bool, str]:
    """키움(KRX) 거래일 여부. DB VERIFIED Calendar만 인정 (Fail Closed)."""

    from datetime import date as date_cls

    import zoneinfo

    tz = zoneinfo.ZoneInfo(get_settings().scheduler_timezone)
    calendar_date = day or datetime.now(tz).date()
    if not isinstance(calendar_date, date_cls):
        calendar_date = calendar_date  # type: ignore[assignment]

    service = TradingCalendarService(
        TradingCalendarRepository(session)
    )
    decision = service.evaluate(
        exchange_code="KRX",
        calendar_date=calendar_date,
    )
    ok = bool(decision.is_trading_day and decision.live_allowed)
    return ok, decision.reason_code


def krx_cron_fallback_gate(
    session: Session,
    *,
    job_id: str,
    job: BrokerRecoverySchedulerJobEntity,
    trigger_type: str = "SCHEDULER",
) -> dict[str, Any] | None:
    """STEP 8-5-13/8-5-15 — 08:30/15:40 고정 Cron이 실제 Session Timeline과

    어긋나는 경우(지연개장/조기종료) 실행을 건너뛴다.
    None을 반환하면 정상 진행.

    STEP 8-5-15 — ``market_session_job_enabled``이면 이 고정 Cron은 더 이상
    Recovery를 직접 실행하지 않는다. 대신 DB Job 존재/기상만 보장
    (``MarketSessionJobService.ensure_wakeup``)하고 실제 실행은 Dispatcher가
    담당한다. ``trigger_type="MARKET_SESSION_JOB"``(Dispatcher가 Handler를
    통해 이 함수를 재호출하는 경로)에는 위임을 적용하지 않아 무한 위임 루프를
    방지한다.
    """

    settings = get_settings()
    if not bool(getattr(settings, "krx_cron_fallback_enabled", True)):
        return None
    if job_id not in (
        "broker_recovery_kiwoom_preopen",
        "broker_recovery_kiwoom_postclose",
    ):
        return None

    try:
        from stock_platform.operation.session_timeline import (
            resolve_krx_timeline,
        )

        timeline = resolve_krx_timeline()
    except Exception:  # noqa: BLE001
        # Timeline 계산 실패 — 기존 is_krx_trading_day Fail Closed에 위임
        return None

    if not timeline.is_trading_day or not timeline.live_allowed:
        # 휴장/Calendar 장애는 상위 is_krx_trading_day 게이트가 이미 처리
        return None

    target = (
        timeline.recovery_preopen_at
        if job_id == "broker_recovery_kiwoom_preopen"
        else timeline.recovery_postclose_at
    )
    if target is None:
        return None

    now = datetime.now(target.tzinfo)
    early_tol = int(
        getattr(settings, "krx_cron_fallback_early_tolerance_minutes", 5)
    )
    late_tol = int(
        getattr(settings, "krx_cron_fallback_late_tolerance_minutes", 60)
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
            "job_id": job_id,
            "target_at": target.isoformat(),
            "now": now.isoformat(),
            "revision": timeline.revision,
        }
    if timing == "TOO_LATE":
        return {
            "status": "SKIPPED_TOO_LATE",
            "job_id": job_id,
            "target_at": target.isoformat(),
            "now": now.isoformat(),
            "revision": timeline.revision,
        }

    last_run_at = getattr(job, "last_run_at", None)
    last_status = str(getattr(job, "last_status", "") or "")
    if (
        last_run_at is not None
        and last_status
        and last_status
        not in {
            "SKIPPED_TOO_EARLY",
            "SKIPPED_TOO_LATE",
            "SKIPPED_DISABLED",
            "SKIPPED_COOLDOWN",
        }
    ):
        last_local = last_run_at.astimezone(target.tzinfo)
        if (
            last_local.date() == target.date()
            and last_local >= target - timedelta(minutes=early_tol)
        ):
            return {
                "status": "SKIPPED_ALREADY_EXECUTED",
                "job_id": job_id,
                "target_at": target.isoformat(),
                "last_run_at": last_run_at.isoformat(),
                "revision": timeline.revision,
            }

    if (
        trigger_type != "MARKET_SESSION_JOB"
        and bool(getattr(settings, "market_session_job_enabled", True))
        and bool(
            getattr(settings, "market_session_cron_wakeup_enabled", True)
        )
    ):
        try:
            from stock_platform.operation.market_session_job_constants import (
                MarketSessionJobType,
            )
            from stock_platform.operation.market_session_job_service import (
                MarketSessionJobService,
            )

            job_type = (
                MarketSessionJobType.KRX_PREOPEN_RECOVERY.value
                if job_id == "broker_recovery_kiwoom_preopen"
                else MarketSessionJobType.KRX_POSTCLOSE_RECOVERY.value
            )
            wakeup = MarketSessionJobService(session).ensure_wakeup(
                exchange_code="KRX",
                job_type=job_type,
                market_date=target.date(),
            )
            return {
                "status": "DELEGATED_TO_MARKET_SESSION_JOB",
                "job_id": job_id,
                "target_at": target.isoformat(),
                "now": now.isoformat(),
                "revision": timeline.revision,
                "wakeup": wakeup,
            }
        except Exception as exc:  # noqa: BLE001
            # 위임 실패 시 레거시 직접 실행으로 Fail Open(Recovery 누락 방지)
            logger.warning(
                "market_session_job_wakeup_delegate_failed",
                job_id=job_id,
                error=str(exc)[:300],
            )
    return None


def classify_krx_calendar_skip(reason: str) -> str:
    """휴장 Skip과 Calendar 장애 Skip을 분리."""

    from stock_platform.operation.calendar_constants import (
        CALENDAR_UNAVAILABLE_REASONS,
    )

    if reason in CALENDAR_UNAVAILABLE_REASONS:
        return "SKIPPED_CALENDAR_UNAVAILABLE"
    return "SKIPPED_MARKET_CLOSED"


def compute_backoff_seconds(
    *,
    retry_count: int,
    base: int,
    maximum: int,
) -> int:
    # 지수 + jitter (폭주 방지)
    exp = min(maximum, int(base * (2 ** max(retry_count - 1, 0))))
    jitter = int(exp * random.uniform(0.0, 0.25))
    return min(maximum, exp + jitter)


def classify_error_code(errors: list[str] | None) -> str | None:
    if not errors:
        return None
    joined = " ".join(str(e) for e in errors).lower()
    for code in NON_RETRYABLE_ERROR_CODES:
        if code in joined:
            return code
    if "manual_review" in joined:
        return "manual_review_required"
    if "429" in joined or "rate limit" in joined:
        return "rate_limit"
    if "timeout" in joined:
        return "timeout"
    if "network" in joined or "connect" in joined:
        return "network_error"
    return "unknown"


async def run_recovery_scheduler_job(
    job_id: str,
    *,
    trigger_type: str = "SCHEDULER",
    requested_by: str = "recovery_scheduler",
    force: bool = False,
) -> dict[str, Any]:
    """단일 Recovery Scheduler Job 실행 (APScheduler / ADMIN 즉시실행 공용)."""

    from stock_platform.broker.recovery_runtime import (
        broker_recovery_manager,
    )

    settings = get_settings()
    session = get_session_factory()()
    try:
        svc = BrokerRecoverySchedulerService(session)
        job = svc.require_job(job_id)
        if not job.is_enabled and not force:
            return {
                "status": "SKIPPED_DISABLED",
                "job_id": job_id,
                "message": "Job disabled",
            }

        # Startup Recovery 직후 Cooldown
        cooldown = int(
            getattr(settings, "recovery_scheduler_startup_cooldown_seconds", 120)
        )
        startup_finished = getattr(
            broker_recovery_manager, "_startup_finished_at", None
        )
        if (
            not force
            and startup_finished is not None
            and (_utcnow() - startup_finished).total_seconds() < cooldown
        ):
            return {
                "status": "SKIPPED_COOLDOWN",
                "job_id": job_id,
                "message": "Startup recovery cooldown active",
            }

        # 키움 CRON: 거래일 게이트 (휴장 vs Calendar 장애 분리)
        if job.broker_code.upper() == "KIWOOM":
            is_open, reason = is_krx_trading_day(session)
            if not is_open and not force:
                skip_status = classify_krx_calendar_skip(reason)
                summary = {
                    "status": skip_status,
                    "job_id": job_id,
                    "reason_code": reason,
                }
                _persist_job_result(
                    session,
                    job,
                    summary,
                    status=(
                        "SKIPPED"
                        if skip_status
                        != "SKIPPED_CALENDAR_UNAVAILABLE"
                        else "SKIPPED_CALENDAR_UNAVAILABLE"
                    ),
                )
                session.commit()
                return summary

            # STEP 8-5-13 — 지연개장/조기종료 등 실제 Timeline과 08:30/15:40
            # 고정 Cron 사이 오차를 허용범위(krx_cron_fallback_*)로 게이트
            if not force:
                fallback_skip = krx_cron_fallback_gate(
                    session,
                    job_id=job_id,
                    job=job,
                    trigger_type=trigger_type,
                )
                if fallback_skip is not None:
                    _persist_job_result(
                        session,
                        job,
                        fallback_skip,
                        status=fallback_skip["status"],
                    )
                    session.commit()
                    return fallback_skip

        broker_filter = job.broker_code.upper()
        if broker_filter == "ALL":
            broker_filter_arg = None
        elif broker_filter == "PAPER":
            broker_filter_arg = "PAPER"
        else:
            broker_filter_arg = broker_filter

        # failed_retry: FAILED+due + LIVE/ARM/conflict 등 safety gate
        retry_targets: list[dict[str, Any]] = []
        retry_skipped: list[dict[str, Any]] = []
        if job_id == "broker_recovery_failed_retry":
            from stock_platform.broker.recovery_scheduler_selector import (
                list_failed_retry_targets,
            )

            retry_targets, retry_skipped = list_failed_retry_targets(session)
            if not retry_targets:
                summary = {
                    "status": "SKIPPED_NO_RETRY_TARGETS",
                    "job_id": job_id,
                    "account_count": 0,
                    "recovery_count": 0,
                    "skipped_gate_count": len(retry_skipped),
                    "recover_all_called": False,
                }
                _persist_job_result(session, job, summary, status="SKIPPED")
                session.commit()
                return summary

        session.commit()  # 설정 읽기 트랜잭션 종료
    finally:
        session.close()

    # Job history + recover
    hist_session = get_session_factory()()
    try:
        job_exec = JobExecutionService(JobRunRepository(hist_session))

        async def _handler() -> dict[str, Any]:
            # 글로벌 중복: recover_all 내부 락
            try:
                if job_id == "broker_recovery_failed_retry":
                    return await _run_failed_retry(
                        retry_targets,
                        concurrency=int(job.concurrency),
                        timeout=float(job.timeout_seconds),
                        max_retries=int(job.max_retries),
                        backoff_base=int(job.backoff_base_seconds),
                        backoff_max=int(job.backoff_max_seconds),
                        requested_by=requested_by,
                    )

                # periodic: broker-wide recover_all 금지 · CHECK_ONLY + expired local finalize
                return await _run_periodic_scoped_job(
                    job_id=job_id,
                    broker_filter=broker_filter_arg,
                    trigger_type=trigger_type,
                )
            except ValueError as exc:
                # 이미 실행 중
                if "already running" in str(exc).lower():
                    return {
                        "status": "SKIPPED_BUSY",
                        "job_id": job_id,
                        "message": str(exc),
                    }
                raise

        history, result = await job_exec.execute(
            job_name=job_id,
            job_group="RECOVERY",
            trigger_type=trigger_type,
            request_payload={
                "job_id": job_id,
                "broker_code": job.broker_code,
                "force": force,
            },
            handler=_handler,
        )
        hist_session.commit()
    except Exception:
        hist_session.rollback()
        raise
    finally:
        hist_session.close()

    # Job 메타 갱신
    meta_session = get_session_factory()()
    try:
        row = BrokerRecoverySchedulerService(meta_session).require_job(
            job_id
        )
        status_code = str(
            (result or {}).get("status")
            or (
                "SUCCESS"
                if (result or {}).get("success")
                else "FAILED"
            )
        )
        _persist_job_result(
            meta_session,
            row,
            result if isinstance(result, dict) else {},
            status=status_code,
        )
        meta_session.commit()
    finally:
        meta_session.close()

    if isinstance(result, dict):
        result["job_run_id"] = getattr(history, "job_run_id", None)
    return result if isinstance(result, dict) else {"result": result}


def _persist_job_result(
    session: Session,
    job: BrokerRecoverySchedulerJobEntity,
    summary: dict[str, Any],
    *,
    status: str,
) -> None:
    job.last_run_at = _utcnow()
    job.last_status = status[:30]
    err = summary.get("message") or summary.get("error")
    if summary.get("failed_count"):
        err = err or f"failed_accounts={summary.get('failed_count')}"
    job.last_error_summary = (
        str(err)[:2000]
        if err
        and status
        not in {
            "SUCCESS",
            "SKIPPED",
            "SKIPPED_NON_TRADING_DAY",
            "SKIPPED_MARKET_CLOSED",
            "SKIPPED_CALENDAR_UNAVAILABLE",
            "SKIPPED_DISABLED",
            "SKIPPED_COOLDOWN",
            "SKIPPED_NO_RETRY_TARGETS",
            "SKIPPED_BUSY",
            "SKIPPED_TOO_EARLY",
            "SKIPPED_TOO_LATE",
            "SKIPPED_ALREADY_EXECUTED",
            "CHECK_ONLY",
            "SKIPPED_NO_RECOVERY_TARGETS",
        }
        else None
    )
    # Secret 없는 요약만
    safe = {
        k: summary.get(k)
        for k in (
            "status",
            "job_id",
            "success",
            "account_count",
            "success_count",
            "failed_count",
            "skipped_count",
            "manual_review_count",
            "timeout_count",
            "skipped_locked_count",
            "reason_code",
            "message",
            "recovery_count",
            "recover_all_called",
            "local_finalize_count",
            "mode",
        )
        if k in summary
    }
    job.last_result_summary = safe
    job.updated_at = _utcnow()


def _summarize_recover_all(
    result: dict[str, Any],
    *,
    job_id: str,
    max_retries: int,
    backoff_base: int,
    backoff_max: int,
) -> dict[str, Any]:
    accounts = list(result.get("accounts") or [])
    success_count = 0
    failed_count = 0
    skipped_count = 0
    manual_review_count = 0
    timeout_count = 0
    skipped_locked_count = 0

    session = get_session_factory()()
    try:
        for row in accounts:
            status = str(row.get("status") or "").upper()
            errors = row.get("errors") or []
            err_text = " ".join(str(e) for e in errors).lower()
            if "already running" in err_text:
                status = "SKIPPED_LOCKED"
                skipped_locked_count += 1
                skipped_count += 1
            elif status in {
                "SKIPPED_LOCKED",
                "SKIPPED_DISTRIBUTED_LOCK",
            }:
                skipped_locked_count += 1
                skipped_count += 1
            elif status == "SKIPPED":
                skipped_count += 1
            elif status == "MANUAL_REVIEW":
                manual_review_count += 1
                failed_count += 1
            elif status in {"SUCCESS", "PARTIAL"}:
                success_count += 1
            else:
                failed_count += 1
                if "timeout" in err_text:
                    timeout_count += 1

            _update_account_retry_state(
                session,
                account_result=row,
                max_retries=max_retries,
                backoff_base=backoff_base,
                backoff_max=backoff_max,
            )
        session.commit()
    finally:
        session.close()

    return {
        "status": (
            "SUCCESS"
            if failed_count == 0 and manual_review_count == 0
            else "PARTIAL" if success_count > 0 else "FAILED"
        ),
        "success": bool(result.get("success")),
        "job_id": job_id,
        "account_count": int(result.get("account_count") or len(accounts)),
        "success_count": success_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "manual_review_count": manual_review_count,
        "timeout_count": timeout_count,
        "skipped_locked_count": skipped_locked_count,
        "started_at": result.get("started_at"),
        "finished_at": result.get("finished_at"),
    }


def _update_account_retry_state(
    session: Session,
    *,
    account_result: dict[str, Any],
    max_retries: int,
    backoff_base: int,
    backoff_max: int,
) -> None:
    uba_id = account_result.get("user_broker_account_id")
    paper_id = account_result.get("paper_account_id")
    broker = str(account_result.get("broker_code") or "").upper()
    if not broker:
        return

    stmt = select(BrokerRecoveryAccountStateEntity).where(
        BrokerRecoveryAccountStateEntity.broker_code == broker
    )
    if uba_id is not None:
        stmt = stmt.where(
            BrokerRecoveryAccountStateEntity.user_broker_account_id
            == int(uba_id)
        )
    elif paper_id is not None:
        stmt = stmt.where(
            BrokerRecoveryAccountStateEntity.paper_account_id
            == int(paper_id)
        )
    else:
        stmt = stmt.where(
            BrokerRecoveryAccountStateEntity.user_broker_account_id.is_(
                None
            ),
            BrokerRecoveryAccountStateEntity.paper_account_id.is_(None),
        )
    row = session.scalar(stmt.limit(1))
    if row is None:
        return

    status = str(account_result.get("status") or "").upper()
    errors = account_result.get("errors") or []
    # credential_error detail
    detail = account_result.get("detail") or {}
    cred = detail.get("credential_error") or {}
    code = cred.get("code") or classify_error_code(errors)

    if status in {"SUCCESS", "PARTIAL", "SKIPPED"}:
        row.retry_count = 0
        row.next_retry_at = None
        row.next_retry_reason = None
        row.last_error_code = None
        row.auto_retry_enabled = True
        return

    if status in {"MANUAL_REVIEW", "BLOCKED_UPBIT_418"} or (
        code and code in NON_RETRYABLE_ERROR_CODES
    ):
        row.last_error_code = code or "manual_review_required"
        row.auto_retry_enabled = False
        row.next_retry_at = None
        if status == "BLOCKED_UPBIT_418":
            row.next_retry_reason = "BLOCKED_UPBIT_418"
        return

    # STEP 8-5-8 — Adapter가 Retry-After 기반 next_retry_at을 이미 기록한 경우
    # 지수 Backoff로 덮어쓰지 않는다.
    if status == "DEFERRED_RATE_LIMIT":
        row.last_error_code = code or "rate_limit"
        row.next_retry_reason = "DEFERRED_RATE_LIMIT"
        row.auto_retry_enabled = True
        if row.next_retry_at is None:
            delay = compute_backoff_seconds(
                retry_count=max(int(row.retry_count or 0), 1),
                base=backoff_base,
                maximum=backoff_max,
            )
            row.next_retry_at = _utcnow() + timedelta(seconds=delay)
        return

    # 재시도 가능
    row.retry_count = int(row.retry_count or 0) + 1
    row.last_error_code = code or "unknown"
    if row.retry_count > max_retries:
        row.auto_retry_enabled = False
        row.next_retry_at = None
        return
    delay = compute_backoff_seconds(
        retry_count=row.retry_count,
        base=backoff_base,
        maximum=backoff_max,
    )
    row.next_retry_at = _utcnow() + timedelta(seconds=delay)
    row.auto_retry_enabled = True
    row.next_retry_reason = "RETRY_SCHEDULED"


def _list_retry_due_accounts(session: Session) -> list[dict[str, Any]]:
    """하위 호환 — safety gate 적용된 failed_retry 대상만."""

    from stock_platform.broker.recovery_scheduler_selector import (
        list_failed_retry_targets,
    )

    eligible, _skipped = list_failed_retry_targets(session)
    return eligible


async def _run_periodic_scoped_job(
    *,
    job_id: str,
    broker_filter: str | None,
    trigger_type: str,
) -> dict[str, Any]:
    """periodic job: broker-wide recover_all 금지.

    - healthy SUCCESS → SKIP / CHECK_ONLY
    - expired RUNNING → local finalize only (broker API 0)
    - FAILED eligible → failed_retry 전담 (여기선 Recovery 0)
    """

    from stock_platform.broker.recovery_lock import RecoveryAccountLockService
    from stock_platform.broker.recovery_scheduler_selector import (
        broker_codes_for_job,
        summarize_periodic_decisions,
    )

    session = get_session_factory()()
    try:
        decision_summary = summarize_periodic_decisions(
            session, broker_filter=broker_filter
        )
        codes = broker_codes_for_job(broker_filter)
        finalize = RecoveryAccountLockService(
            session
        ).finalize_expired_orphan_states(
            actor=f"SCHEDULER:{job_id}",
            broker_codes=codes,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    finalized = int(finalize.get("finalized") or 0)
    return {
        "status": "CHECK_ONLY",
        "success": True,
        "job_id": job_id,
        "trigger_type": trigger_type,
        "mode": "CHECK_ONLY",
        "broker_code": broker_filter,
        "account_count": 0,
        "success_count": 0,
        "failed_count": 0,
        "skipped_count": int(
            sum(
                (decision_summary.get("decision_counts") or {}).values()
            )
        ),
        "manual_review_count": 0,
        "timeout_count": 0,
        "skipped_locked_count": 0,
        "recovery_count": 0,
        "recover_all_called": False,
        "local_finalize_count": finalized,
        "local_finalize": finalize,
        "decision_counts": decision_summary.get("decision_counts") or {},
        "message": (
            "periodic full Recovery disabled; "
            "healthy accounts CHECK_ONLY; "
            "expired RUNNING local-finalize only"
        ),
        "started_at": _utcnow().isoformat(),
        "finished_at": _utcnow().isoformat(),
    }


async def _run_failed_retry(
    targets: list[dict[str, Any]],
    *,
    concurrency: int,
    timeout: float,
    max_retries: int,
    backoff_base: int,
    backoff_max: int,
    requested_by: str,
) -> dict[str, Any]:
    from stock_platform.broker.recovery_runtime import (
        broker_recovery_manager,
    )

    # 계좌별 recover_all 호출 (필터) — 병렬은 recover_all 내부
    # 대상이 섞여 있으면 개별 호출
    accounts_out: list[dict[str, Any]] = []
    for target in targets:
        # Credential 비재시도 코드면 skip
        code = None
        try:
            result = await broker_recovery_manager.recover_all(
                trigger_type="SCHEDULER_RETRY",
                broker_code=target["broker_code"],
                paper_account_id=target.get("paper_account_id"),
                user_broker_account_id=target.get(
                    "user_broker_account_id"
                ),
                requested_by=requested_by,
                concurrency=1,
                overall_timeout_seconds=timeout,
            )
            accounts_out.extend(result.get("accounts") or [])
        except ValueError as exc:
            if "already running" in str(exc).lower():
                accounts_out.append(
                    {
                        "status": "SKIPPED_LOCKED",
                        "errors": [str(exc)],
                        **{
                            k: target.get(k)
                            for k in (
                                "broker_code",
                                "paper_account_id",
                                "user_broker_account_id",
                            )
                        },
                    }
                )
            else:
                raise

    wrapped = {
        "success": all(
            a.get("status")
            in {
                "SUCCESS",
                "PARTIAL",
                "SKIPPED",
                "SKIPPED_LOCKED",
                "SKIPPED_DISTRIBUTED_LOCK",
            }
            for a in accounts_out
        )
        if accounts_out
        else True,
        "account_count": len(accounts_out),
        "accounts": accounts_out,
        "started_at": _utcnow().isoformat(),
        "finished_at": _utcnow().isoformat(),
    }
    return _summarize_recover_all(
        wrapped,
        job_id="broker_recovery_failed_retry",
        max_retries=max_retries,
        backoff_base=backoff_base,
        backoff_max=backoff_max,
    ) | {
        "recovery_count": len(accounts_out),
        "recover_all_called": True,
        "mode": "TARGETED_FAILED_RETRY",
    }


def uba_credential_ready(session: Session, uba_id: int) -> bool:
    """LIVE UBA 외부 Recovery 전 Credential VERIFIED 여부."""

    status = BrokerCredentialVaultService(session).status(uba_id)
    return bool(
        status.connected
        and status.is_active
        and status.verification_status == "VERIFIED"
    )
