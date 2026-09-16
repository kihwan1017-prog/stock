"""체크 실행 헬퍼."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from stock_platform.operations.rehearsal.models import (
    CheckResult,
    CheckStatus,
)


def run_check(
    *,
    suite: str,
    name: str,
    fn: Callable[[], tuple[CheckStatus, str, dict[str, Any]]],
) -> CheckResult:
    started = time.perf_counter()
    try:
        status, message, detail = fn()
    except Exception as exc:  # noqa: BLE001
        status = CheckStatus.FAIL
        message = f"{type(exc).__name__}: {exc}"[:300]
        detail = {"exception_type": type(exc).__name__}
    duration_ms = (time.perf_counter() - started) * 1000.0
    return CheckResult(
        suite=suite,
        name=name,
        status=status,
        message=message,
        detail=detail,
        duration_ms=round(duration_ms, 2),
    )
