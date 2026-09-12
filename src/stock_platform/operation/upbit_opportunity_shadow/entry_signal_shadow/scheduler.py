"""Entry signal shadow outcome maturation — research-only interval job."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import func, select

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.constants import (
    OUTCOME_WINDOWS_MIN,
    STATUS_PENDING,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.entities import (
    UpbitEntrySignalShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.service import (
    mature_pending_outcomes,
)

logger = structlog.get_logger(__name__)

# 프로세스 내 관측용 (DB가 SoT, 재시작 시 카운터 리셋)
_RUNTIME: dict[str, Any] = {
    "configured": False,
    "run_count": 0,
    "success_count": 0,
    "error_count": 0,
    "rows_scanned": 0,
    "rows_updated": 0,
    "last_run_at": None,
    "last_success_at": None,
    "last_error": None,
    "last_result": None,
}


def runtime_status() -> dict[str, Any]:
    return dict(_RUNTIME)


def run_entry_signal_shadow_outcome_tick(
    settings: Any | None = None,
) -> dict[str, Any]:
    """PENDING + age>=60m shadow row outcome 채움. REAL mutation 0."""

    settings = settings or get_settings()
    if not bool(getattr(settings, "upbit_entry_signal_shadow_enabled", True)):
        return {"ok": False, "reason": "DISABLED"}

    _RUNTIME["run_count"] = int(_RUNTIME["run_count"] or 0) + 1
    _RUNTIME["last_run_at"] = datetime.now(timezone.utc).isoformat()

    factory = get_session_factory()
    try:
        with factory() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(
                minutes=min(OUTCOME_WINDOWS_MIN)
            )
            scanned = session.scalar(
                select(func.count())
                .select_from(UpbitEntrySignalShadowEntity)
                .where(
                    UpbitEntrySignalShadowEntity.outcome_status == STATUS_PENDING,
                    UpbitEntrySignalShadowEntity.observed_at <= cutoff,
                )
            )
            result = mature_pending_outcomes(session, limit=500, commit=True)
            # Entry Gate V2 outcome maturation — same tick, fail-open
            try:
                from stock_platform.operation.upbit_opportunity_shadow.entry_gate_v2.service import (
                    mature_pending_v2_outcomes,
                )

                if bool(
                    getattr(settings, "upbit_entry_gate_v2_shadow_enabled", True)
                ):
                    mature_pending_v2_outcomes(session, limit=200, commit=True)
            except Exception:  # noqa: BLE001
                pass
            updated = int(result.get("matured") or 0) + int(
                result.get("insufficient") or 0
            )
            _RUNTIME["rows_scanned"] = int(scanned or 0)
            _RUNTIME["rows_updated"] = int(_RUNTIME.get("rows_updated") or 0) + updated
            _RUNTIME["last_result"] = result
            _RUNTIME["last_success_at"] = datetime.now(timezone.utc).isoformat()
            _RUNTIME["success_count"] = int(_RUNTIME["success_count"] or 0) + 1
            _RUNTIME["last_error"] = None
            return {
                "ok": True,
                "scanned": int(scanned or 0),
                **result,
                "orders_created": 0,
                "research_only": True,
            }
    except Exception as exc:  # noqa: BLE001
        _RUNTIME["error_count"] = int(_RUNTIME["error_count"] or 0) + 1
        _RUNTIME["last_error"] = f"{type(exc).__name__}:{str(exc)[:160]}"
        logger.warning(
            "entry_signal_shadow_outcome_tick_failed",
            error=type(exc).__name__,
        )
        return {
            "ok": False,
            "error": type(exc).__name__,
            "orders_created": 0,
            "research_only": True,
        }


class UpbitEntrySignalShadowOutcomeScheduler:
    """경량 interval job — ma_exit_forward_shadow 패턴 미러."""

    JOB_ID = "upbit_entry_signal_shadow_outcome"

    def __init__(self) -> None:
        self._configured = False

    def configure(self, scheduler: Any) -> None:
        if self._configured:
            return
        settings = get_settings()
        if not bool(getattr(settings, "upbit_entry_signal_shadow_enabled", True)):
            self._configured = True
            _RUNTIME["configured"] = True
            return
        interval = int(
            getattr(settings, "upbit_entry_signal_shadow_interval_seconds", 120)
            or 120
        )
        interval = max(60, min(300, interval))

        def _job() -> None:
            try:
                run_entry_signal_shadow_outcome_tick(settings)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "entry_signal_shadow_outcome_scheduler_error",
                    error=str(exc)[:200],
                )

        scheduler.add_job(
            _job,
            "interval",
            seconds=interval,
            id=self.JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._configured = True
        _RUNTIME["configured"] = True
        logger.info(
            "entry_signal_shadow_outcome_scheduler_configured",
            interval_seconds=interval,
            job_id=self.JOB_ID,
        )
