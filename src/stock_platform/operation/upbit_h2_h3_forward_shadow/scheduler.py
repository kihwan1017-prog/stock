"""H2/H3 forward-shadow interval job — research only, no StrategySignal."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.operation.upbit_h2_h3_forward_shadow.service import (
    run_evaluate_tick,
)

logger = structlog.get_logger(__name__)

_RUNTIME: dict[str, Any] = {
    "configured": False,
    "run_count": 0,
    "success_count": 0,
    "error_count": 0,
    "last_run_at": None,
    "last_success_at": None,
    "last_error": None,
    "last_result": None,
    "strategy_signal_published": 0,
    "executor_calls": 0,
    "real_orders": 0,
}


def runtime_status() -> dict[str, Any]:
    return dict(_RUNTIME)


def run_h2_h3_forward_shadow_tick(settings: Any | None = None) -> dict[str, Any]:
    """Evaluate + mature. Never publishes signals or creates orders."""

    settings = settings or get_settings()
    if not bool(getattr(settings, "upbit_h2_h3_forward_shadow_enabled", True)):
        return {"ok": False, "reason": "DISABLED", "research_only": True}

    _RUNTIME["run_count"] = int(_RUNTIME["run_count"] or 0) + 1
    _RUNTIME["last_run_at"] = datetime.now(timezone.utc).isoformat()

    factory = get_session_factory()
    try:
        with factory() as session:
            result = run_evaluate_tick(session)
            _RUNTIME["last_result"] = result
            _RUNTIME["last_success_at"] = datetime.now(timezone.utc).isoformat()
            _RUNTIME["success_count"] = int(_RUNTIME["success_count"] or 0) + 1
            _RUNTIME["last_error"] = None
            _RUNTIME["strategy_signal_published"] = 0
            _RUNTIME["executor_calls"] = 0
            _RUNTIME["real_orders"] = 0
            return {
                "ok": True,
                **result,
                "research_only": True,
                "orders_created": 0,
            }
    except Exception as exc:  # noqa: BLE001
        _RUNTIME["error_count"] = int(_RUNTIME["error_count"] or 0) + 1
        _RUNTIME["last_error"] = f"{type(exc).__name__}:{str(exc)[:160]}"
        logger.warning(
            "h2_h3_forward_shadow_tick_failed",
            error=type(exc).__name__,
        )
        return {
            "ok": False,
            "error": type(exc).__name__,
            "orders_created": 0,
            "research_only": True,
        }


class UpbitH2H3ForwardShadowScheduler:
    """경량 interval — production scanner path와 분리."""

    JOB_ID = "upbit_h2_h3_forward_shadow"

    def __init__(self) -> None:
        self._configured = False

    def configure(self, scheduler: Any) -> None:
        if self._configured:
            return
        settings = get_settings()
        if not bool(getattr(settings, "upbit_h2_h3_forward_shadow_enabled", True)):
            self._configured = True
            _RUNTIME["configured"] = True
            return
        interval = int(
            getattr(settings, "upbit_h2_h3_forward_shadow_interval_seconds", 180)
            or 180
        )
        interval = max(60, min(300, interval))

        def _job() -> None:
            try:
                run_h2_h3_forward_shadow_tick(settings)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "h2_h3_forward_shadow_scheduler_error",
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
            "h2_h3_forward_shadow_scheduler_configured",
            interval_seconds=interval,
            job_id=self.JOB_ID,
            research_only=True,
        )
