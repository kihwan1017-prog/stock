"""STEP 8-5-15 — Market Session Job Dispatcher (Due Poll → Claim → Handle).

Claim은 반드시 짧은 트랜잭션의 단일 `UPDATE ... RETURNING`으로 수행하고,
Handler 실행은 별도 세션에서 이뤄진다 (원격 호출·재시도로 오래 걸릴 수
있으므로 Claim Row Lock을 오래 들고 있지 않는다). 최종 상태 반영 직전에는
`run_token`을 재검증해 Ownership이 유지됐는지 확인한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text

from stock_platform.broker.recovery_instance_id import (
    get_recovery_instance_identity,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.market_session_job_constants import (
    MarketSessionJobResult,
    MarketSessionJobStatus,
)
from stock_platform.operation.market_session_job_entities import (
    MarketSessionJobEntity,
)
from stock_platform.operation.market_session_job_handlers import (
    MarketSessionJobHandlerOutcome,
    get_handler,
)
from stock_platform.operation.market_session_job_service import (
    MarketSessionJobError,
    MarketSessionJobService,
)

logger = structlog.get_logger(__name__)

_SKIPPED_RESULT_CODES = frozenset(
    {
        MarketSessionJobResult.SKIPPED.value,
        MarketSessionJobResult.SKIPPED_TOO_LATE.value,
        MarketSessionJobResult.SKIPPED_ALREADY_EXISTS.value,
        MarketSessionJobResult.SKIPPED_DEPENDENCY.value,
        MarketSessionJobResult.SETTLEMENT_NOOP.value,
        MarketSessionJobResult.DEFERRED_TO_CRON.value,
    }
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _compute_backoff_seconds(*, attempt: int, base: int, maximum: int) -> int:
    exp = min(maximum, int(base * (2 ** max(attempt - 1, 0))))
    return max(base, exp)


def wake_job(job_key: str) -> None:
    """DateTrigger Wake-up 훅 — DB Claim 기반이므로 실질 실행은 Poller가 담당.

    별도 즉시 실행을 강제하지 않고 로그만 남긴다. Poller 주기
    (``market_session_job_dispatcher_poll_seconds``, 기본 5초) 내에 자연히
    Claim된다.
    """

    logger.info("market_session_job_wake_up", job_key=job_key)


class MarketSessionJobDispatcher:
    def __init__(self) -> None:
        self._instance_id = get_recovery_instance_identity().instance_id

    @property
    def instance_id(self) -> str:
        return self._instance_id

    async def run_once(
        self, *, batch_size: int | None = None
    ) -> dict[str, Any]:
        settings = get_settings()
        if not bool(settings.market_session_job_enabled):
            return {"status": "DISABLED", "processed": 0}

        size = int(batch_size or settings.market_session_job_batch_size)
        session = get_session_factory()()
        try:
            due_ids = MarketSessionJobService(session).select_due_job_ids(
                limit=size
            )
        finally:
            session.close()

        if not due_ids:
            return {"status": "NO_DUE", "processed": 0}

        results = [await self._process_one(job_id) for job_id in due_ids]
        return {
            "status": "OK",
            "processed": len(results),
            "results": results,
        }

    async def _process_one(self, job_id: int) -> dict[str, Any]:
        settings = get_settings()
        session = get_session_factory()()
        try:
            svc = MarketSessionJobService(session)
            run_token = svc.try_claim(
                job_id,
                instance_id=self._instance_id,
                claim_seconds=int(settings.market_session_job_claim_seconds),
            )
            if run_token is None:
                return {"job_id": job_id, "status": "CLAIM_LOST"}
            svc.mark_running(job_id, run_token=run_token)
        finally:
            session.close()

        started_at = _utcnow()
        outcome = await self._invoke_handler(job_id)
        return await self._finalize(
            job_id, run_token=run_token, started_at=started_at, outcome=outcome
        )

    async def _invoke_handler(
        self, job_id: int
    ) -> MarketSessionJobHandlerOutcome:
        session = get_session_factory()()
        try:
            job = session.get(MarketSessionJobEntity, int(job_id))
            if job is None:
                return MarketSessionJobHandlerOutcome(
                    result_code=MarketSessionJobResult.FAILED.value,
                    error_code="JOB_NOT_FOUND",
                    error_summary="job not found",
                )
            handler = get_handler(job.job_type)
            if handler is None:
                return MarketSessionJobHandlerOutcome(
                    result_code=MarketSessionJobResult.FAILED.value,
                    error_code="NO_HANDLER",
                    error_summary=f"no handler for {job.job_type}",
                )
            try:
                outcome = await handler.handle(session, job)
                session.commit()
                return outcome
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                logger.warning(
                    "market_session_job_handler_error",
                    job_id=job_id,
                    error=str(exc)[:300],
                )
                return MarketSessionJobHandlerOutcome(
                    result_code=MarketSessionJobResult.FAILED.value,
                    error_code="HANDLER_EXCEPTION",
                    error_summary=str(exc)[:400],
                )
        finally:
            session.close()

    async def _finalize(
        self,
        job_id: int,
        *,
        run_token: str,
        started_at: datetime,
        outcome: MarketSessionJobHandlerOutcome,
    ) -> dict[str, Any]:
        settings = get_settings()
        session = get_session_factory()()
        try:
            svc = MarketSessionJobService(session)
            job = svc.get(job_id)
            if job is None:
                return {"job_id": job_id, "status": "NOT_FOUND"}

            result_code = outcome.result_code
            attempt = int(job.attempt_count) + 1
            next_retry_at: datetime | None = None

            if result_code == MarketSessionJobResult.SUCCEEDED.value:
                final_status = MarketSessionJobStatus.SUCCEEDED.value
            elif result_code in _SKIPPED_RESULT_CODES:
                final_status = MarketSessionJobStatus.SKIPPED.value
            elif result_code == MarketSessionJobResult.RETRY.value:
                final_status = MarketSessionJobStatus.RETRY_PENDING.value
                delay = outcome.retry_after_seconds or (
                    _compute_backoff_seconds(
                        attempt=attempt,
                        base=int(
                            settings.market_session_job_retry_base_seconds
                        ),
                        maximum=int(
                            settings.market_session_job_retry_max_seconds
                        ),
                    )
                )
                next_retry_at = _utcnow() + timedelta(seconds=delay)
            else:  # FAILED
                if attempt >= int(job.max_attempts):
                    final_status = MarketSessionJobStatus.FAILED.value
                else:
                    final_status = MarketSessionJobStatus.RETRY_PENDING.value
                    delay = _compute_backoff_seconds(
                        attempt=attempt,
                        base=int(
                            settings.market_session_job_retry_base_seconds
                        ),
                        maximum=int(
                            settings.market_session_job_retry_max_seconds
                        ),
                    )
                    next_retry_at = _utcnow() + timedelta(seconds=delay)

            finished_at = _utcnow()
            ok = svc.finish_job(
                job_id,
                run_token=run_token,
                status_code=final_status,
                error_code=outcome.error_code,
                error_summary=(
                    outcome.error_summary or outcome.result_summary
                ),
                next_retry_at=next_retry_at,
            )
            record_status = final_status if ok else "OWNERSHIP_LOST"
            svc.record_run(
                job_id=job_id,
                run_number=attempt,
                instance_id=self._instance_id,
                run_token=run_token,
                started_at=started_at,
                finished_at=finished_at,
                status_code=record_status,
                result_code=result_code,
                result_summary=outcome.result_summary,
                error_code=outcome.error_code
                or (None if ok else "OWNERSHIP_LOST"),
                error_summary=outcome.error_summary,
                calendar_revision=int(job.calendar_revision),
                scheduled_for=job.scheduled_for,
            )
            if not ok:
                logger.warning(
                    "market_session_job_ownership_lost", job_id=job_id
                )
                return {"job_id": job_id, "status": "OWNERSHIP_LOST"}
            return {
                "job_id": job_id,
                "status": final_status,
                "result_code": result_code,
            }
        finally:
            session.close()

    # ------------------------------------------------------------------
    # ADMIN 즉시 실행
    # ------------------------------------------------------------------

    async def run_now(self, job_id: int, *, actor: str) -> dict[str, Any]:
        """scheduled_for를 무시하고 즉시 Claim + 실행 (이미 진행 중이면 거부)."""

        session = get_session_factory()()
        try:
            svc = MarketSessionJobService(session)
            job = svc.get(job_id)
            if job is None:
                raise MarketSessionJobError("not_found", "Job not found")
            active_claim = (
                job.status_code
                in {
                    MarketSessionJobStatus.CLAIMED.value,
                    MarketSessionJobStatus.RUNNING.value,
                }
                and job.claim_expires_at is not None
                and job.claim_expires_at > _utcnow()
            )
            if active_claim:
                raise MarketSessionJobError(
                    "busy", "Job already claimed/running"
                )
        finally:
            session.close()

        run_token = self._force_claim(job_id, actor=actor)
        if run_token is None:
            raise MarketSessionJobError(
                "claim_failed", "Could not claim job for run-now"
            )
        started_at = _utcnow()
        outcome = await self._invoke_handler(job_id)
        return await self._finalize(
            job_id, run_token=run_token, started_at=started_at, outcome=outcome
        )

    def _force_claim(self, job_id: int, *, actor: str) -> str | None:
        settings = get_settings()
        run_token = uuid.uuid4().hex
        session = get_session_factory()()
        try:
            row = session.execute(
                text(
                    """
                    UPDATE operation.market_session_job
                    SET status_code = 'CLAIMED',
                        claimed_by = :owner,
                        claimed_at = NOW(),
                        claim_expires_at =
                            NOW() + make_interval(secs => :secs),
                        run_token = :run_token,
                        updated_at = NOW()
                    WHERE market_session_job_id = :job_id
                      AND (
                        status_code NOT IN ('CLAIMED', 'RUNNING')
                        OR (
                            claim_expires_at IS NOT NULL
                            AND claim_expires_at < NOW()
                        )
                      )
                    RETURNING market_session_job_id
                    """
                ),
                {
                    "owner": f"admin:{actor}"[:200],
                    "secs": int(
                        settings.market_session_job_claim_seconds
                    ),
                    "run_token": run_token,
                    "job_id": int(job_id),
                },
            ).first()
            session.commit()
            return run_token if row is not None else None
        finally:
            session.close()


market_session_job_dispatcher = MarketSessionJobDispatcher()
