"""STEP 8-5-15 — Market Session Job Handler Protocol + Registry.

각 Handler는 실제 업무 로직을 호출하고 결과를 `MarketSessionJobHandlerOutcome`
으로 반환한다. 상태 전이(SUCCEEDED/FAILED/RETRY_PENDING 등)는 Dispatcher가
Outcome을 보고 최종 결정한다 — Handler는 판단 재료만 제공한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy.orm import Session

from stock_platform.operation.market_session_job_constants import (
    ACTIVE_JOB_STATUSES,
    MarketSessionJobResult,
    MarketSessionJobType,
)
from stock_platform.operation.market_session_job_entities import (
    MarketSessionJobEntity,
)


@dataclass(slots=True)
class MarketSessionJobHandlerOutcome:
    result_code: str
    result_summary: str = ""
    error_code: str | None = None
    error_summary: str | None = None
    retry_after_seconds: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)


class MarketSessionJobHandler(Protocol):
    async def handle(
        self, session: Session, job: MarketSessionJobEntity
    ) -> MarketSessionJobHandlerOutcome: ...


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _KiwoomRecoveryHandlerBase:
    """Preopen/Postclose 공통 — 기존 `run_recovery_scheduler_job` 재사용."""

    _job_id: str
    _timeline_field: str

    async def _resolve_timeline(self, job: MarketSessionJobEntity):
        try:
            from stock_platform.operation.session_timeline import (
                resolve_krx_timeline,
            )

            return resolve_krx_timeline(market_date=job.market_date)
        except Exception:  # noqa: BLE001
            return None

    async def handle(
        self, session: Session, job: MarketSessionJobEntity
    ) -> MarketSessionJobHandlerOutcome:
        from stock_platform.broker.recovery_scheduler_service import (
            run_recovery_scheduler_job,
        )

        result = await run_recovery_scheduler_job(
            self._job_id,
            trigger_type="MARKET_SESSION_JOB",
            requested_by=(
                f"market_session_job:{job.market_session_job_id}"
            ),
        )
        status = str(result.get("status") or "")
        if status.startswith("SKIPPED"):
            return MarketSessionJobHandlerOutcome(
                result_code=MarketSessionJobResult.SKIPPED.value,
                result_summary=status,
                detail=result,
            )
        return MarketSessionJobHandlerOutcome(
            result_code=MarketSessionJobResult.SUCCEEDED.value,
            result_summary=status or "OK",
            detail=result,
        )


class KrxPreopenRecoveryHandler(_KiwoomRecoveryHandlerBase):
    _job_id = "broker_recovery_kiwoom_preopen"
    _timeline_field = "regular_open_at"

    async def handle(
        self, session: Session, job: MarketSessionJobEntity
    ) -> MarketSessionJobHandlerOutcome:
        timeline = await self._resolve_timeline(job)
        now = _utcnow()
        if timeline is not None and timeline.regular_open_at is not None:
            if now >= timeline.regular_open_at:
                return MarketSessionJobHandlerOutcome(
                    result_code=(
                        MarketSessionJobResult.SKIPPED_TOO_LATE.value
                    ),
                    result_summary=(
                        "market already open — preopen recovery skipped"
                    ),
                )
        return await super().handle(session, job)


class KrxPostcloseRecoveryHandler(_KiwoomRecoveryHandlerBase):
    _job_id = "broker_recovery_kiwoom_postclose"
    _timeline_field = "recovery_postclose_at"

    async def handle(
        self, session: Session, job: MarketSessionJobEntity
    ) -> MarketSessionJobHandlerOutcome:
        from stock_platform.common.settings import get_settings

        timeline = await self._resolve_timeline(job)
        now = _utcnow()
        late_tol = int(
            getattr(
                get_settings(),
                "krx_cron_fallback_late_tolerance_minutes",
                60,
            )
        )
        target = (
            timeline.recovery_postclose_at if timeline is not None else None
        )
        if target is not None and now > target + timedelta(
            minutes=late_tol
        ):
            return MarketSessionJobHandlerOutcome(
                result_code=MarketSessionJobResult.SKIPPED_TOO_LATE.value,
                result_summary="postclose late tolerance exceeded",
            )
        return await super().handle(session, job)


class KrxEquitySnapshotHandler:
    async def handle(
        self, session: Session, job: MarketSessionJobEntity
    ) -> MarketSessionJobHandlerOutcome:
        from stock_platform.operation.job_repository import (
            JobRunRepository,
        )
        from stock_platform.scheduler.service import SchedulerService

        recent = JobRunRepository(session).list_recent(
            job_name="portfolio_equity_snapshot",
            status_code="SUCCESS",
            limit=5,
        )
        for run in recent:
            started = run.started_at
            if started is None:
                continue
            if started.date() == job.market_date:
                return MarketSessionJobHandlerOutcome(
                    result_code=(
                        MarketSessionJobResult.SKIPPED_ALREADY_EXISTS.value
                    ),
                    result_summary=(
                        f"snapshot already captured at {started.isoformat()}"
                    ),
                )

        history, result = await SchedulerService(session).execute(
            job_name="portfolio_equity_snapshot",
            payload={
                "snapshot_date": job.market_date.isoformat(),
                "include_live": True,
            },
            trigger_type="MARKET_SESSION_JOB",
        )
        return MarketSessionJobHandlerOutcome(
            result_code=MarketSessionJobResult.SUCCEEDED.value,
            result_summary=f"job_run_id={history.job_run_id}",
            detail=result if isinstance(result, dict) else {},
        )


class KrxSettlementHandler:
    """STEP 8-5-16/17 — KRX EOD 실정산 (Snapshot Dependency + UBA Binding)."""

    async def handle(
        self, session: Session, job: MarketSessionJobEntity
    ) -> MarketSessionJobHandlerOutcome:
        # Snapshot Job 성공 의존
        if job.depends_on_job_id is not None:
            dep = session.get(
                MarketSessionJobEntity, int(job.depends_on_job_id)
            )
            if dep is not None:
                if dep.status_code in ACTIVE_JOB_STATUSES:
                    return MarketSessionJobHandlerOutcome(
                        result_code=MarketSessionJobResult.RETRY.value,
                        result_summary=(
                            "dependency snapshot job still pending"
                        ),
                        retry_after_seconds=30,
                    )
                if dep.status_code in {
                    "FAILED",
                    "SKIPPED",
                    "EXPIRED",
                    "CANCELLED",
                }:
                    return MarketSessionJobHandlerOutcome(
                        result_code=(
                            MarketSessionJobResult.SKIPPED_DEPENDENCY.value
                        ),
                        result_summary=(
                            f"dependency snapshot job ended {dep.status_code}"
                        ),
                    )

        from stock_platform.settlement.runner import run_krx_eod_settlement

        summary = run_krx_eod_settlement(
            session,
            market_date=job.market_date,
            calendar_revision=int(job.calendar_revision or 0) or None,
            actor=f"JOB:{job.job_key}",
        )
        counts = summary.get("counts") or {}
        retry = int(counts.get("retry") or 0)
        failed = int(counts.get("failed") or 0)
        manual = int(counts.get("manual_review") or 0)
        total = int(counts.get("total") or 0)

        if total == 0:
            return MarketSessionJobHandlerOutcome(
                result_code=MarketSessionJobResult.SUCCEEDED.value,
                result_summary="no settlement targets",
                detail=summary,
            )
        if retry > 0 and failed == 0 and manual == 0:
            return MarketSessionJobHandlerOutcome(
                result_code=MarketSessionJobResult.RETRY.value,
                result_summary=f"retry_pending={retry}",
                retry_after_seconds=60,
                detail=summary,
            )
        if failed > 0 and (counts.get("succeeded") or 0) == 0:
            return MarketSessionJobHandlerOutcome(
                result_code=MarketSessionJobResult.FAILED.value,
                result_summary=f"failed={failed}",
                detail=summary,
            )
        # 일부 Manual Review / Warning이 있어도 Job 자체는 완료로 집계
        return MarketSessionJobHandlerOutcome(
            result_code=MarketSessionJobResult.SUCCEEDED.value,
            result_summary=(
                f"total={total} ok={counts.get('succeeded', 0)} "
                f"warn={counts.get('warnings', 0)} "
                f"manual={manual} failed={failed}"
            ),
            detail=summary,
        )


class KrxAiAnalysisHandler:
    async def handle(
        self, session: Session, job: MarketSessionJobEntity
    ) -> MarketSessionJobHandlerOutcome:
        if job.depends_on_job_id is not None:
            dep = session.get(
                MarketSessionJobEntity, int(job.depends_on_job_id)
            )
            if dep is not None:
                if dep.status_code in ACTIVE_JOB_STATUSES:
                    return MarketSessionJobHandlerOutcome(
                        result_code=MarketSessionJobResult.RETRY.value,
                        result_summary=(
                            "dependency snapshot job still pending"
                        ),
                        retry_after_seconds=30,
                    )
                if dep.status_code in {"FAILED", "SKIPPED", "EXPIRED", "CANCELLED"}:
                    return MarketSessionJobHandlerOutcome(
                        result_code=(
                            MarketSessionJobResult.SKIPPED_DEPENDENCY.value
                        ),
                        result_summary=(
                            f"dependency snapshot job ended {dep.status_code}"
                        ),
                    )

        from stock_platform.common.settings import get_settings
        from stock_platform.scheduler.service import SchedulerService

        settings = get_settings()
        history, result = await SchedulerService(session).execute(
            job_name="ai_orchestration",
            payload={
                "exchange_code": settings.scheduler_exchange_code,
                "limit": settings.scheduler_ai_limit,
                "news_limit": 20,
                "disclosure_limit": 20,
                "lookback_days": 90,
                "minimum_ai_score": settings.scheduler_minimum_ai_score,
                "minimum_confidence": settings.scheduler_minimum_confidence,
            },
            trigger_type="MARKET_SESSION_JOB",
        )
        return MarketSessionJobHandlerOutcome(
            result_code=MarketSessionJobResult.SUCCEEDED.value,
            result_summary=f"job_run_id={history.job_run_id}",
            detail=result if isinstance(result, dict) else {},
        )


_HANDLER_REGISTRY: dict[str, MarketSessionJobHandler] = {
    MarketSessionJobType.KRX_PREOPEN_RECOVERY.value: (
        KrxPreopenRecoveryHandler()
    ),
    MarketSessionJobType.KRX_POSTCLOSE_RECOVERY.value: (
        KrxPostcloseRecoveryHandler()
    ),
    MarketSessionJobType.KRX_EQUITY_SNAPSHOT.value: (
        KrxEquitySnapshotHandler()
    ),
    MarketSessionJobType.KRX_SETTLEMENT.value: KrxSettlementHandler(),
    MarketSessionJobType.KRX_AI_ANALYSIS.value: KrxAiAnalysisHandler(),
}


def get_handler(job_type: str) -> MarketSessionJobHandler | None:
    return _HANDLER_REGISTRY.get(job_type)
