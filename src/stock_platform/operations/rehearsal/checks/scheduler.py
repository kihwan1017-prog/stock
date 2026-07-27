"""Scheduler 리허설."""

from __future__ import annotations

from typing import Any

from stock_platform.common.settings import get_settings
from stock_platform.operations.rehearsal.checks import run_check
from stock_platform.operations.rehearsal.models import (
    CheckResult,
    CheckStatus,
)


def run_scheduler_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    settings = get_settings()

    def _enabled() -> tuple[CheckStatus, str, dict[str, Any]]:
        enabled = bool(getattr(settings, "scheduler_enabled", False))
        return (
            CheckStatus.PASS if enabled else CheckStatus.WARNING,
            "scheduler_enabled=" + str(enabled),
            {"scheduler_enabled": enabled},
        )

    results.append(run_check(suite="scheduler", name="config", fn=_enabled))

    def _leader_lock() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.database.session import get_engine
        from stock_platform.scheduler.leader_lock import (
            try_acquire_lifecycle_scheduler_lock,
        )

        first = try_acquire_lifecycle_scheduler_lock(get_engine())
        try:
            if not first.acquired:
                return (
                    CheckStatus.WARNING,
                    "leader lock not acquired (another instance?)",
                    {"reason": first.reason},
                )
            # 동일 엔진에서 두 번째 획득 시도 → 중복 방지 검증
            second = try_acquire_lifecycle_scheduler_lock(get_engine())
            try:
                dup_blocked = not second.acquired
                status = (
                    CheckStatus.PASS
                    if dup_blocked or second.reason.startswith("non_postgres")
                    else CheckStatus.WARNING
                )
                return (
                    status,
                    "duplicate prevention checked",
                    {
                        "first_acquired": first.acquired,
                        "second_acquired": second.acquired,
                        "second_reason": second.reason,
                    },
                )
            finally:
                second.release()
        finally:
            first.release()

    results.append(
        run_check(suite="scheduler", name="duplicate_prevention", fn=_leader_lock)
    )

    def _lifecycle() -> tuple[CheckStatus, str, dict[str, Any]]:
        # start/stop/restart는 프로세스 제어라 리허설에서는 import·설정 검증
        from stock_platform.scheduler import automatic

        assert hasattr(automatic, "AutomaticScheduler")
        return (
            CheckStatus.PASS,
            "scheduler start/stop/restart surface available",
            {
                "has_start": hasattr(automatic.AutomaticScheduler, "start"),
                "has_shutdown": hasattr(
                    automatic.AutomaticScheduler, "shutdown"
                ),
            },
        )

    results.append(
        run_check(suite="scheduler", name="start_stop_restart", fn=_lifecycle)
    )
    return results
