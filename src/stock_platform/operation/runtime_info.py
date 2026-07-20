"""프로세스 런타임 정보 — uptime / version / git (STEP61)."""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from stock_platform.common.settings import get_settings

# 모듈 로드 시각 (lifespan 전에도 의미 있음)
_MODULE_STARTED_MONOTONIC = time.monotonic()
_PROCESS_STARTED_AT = datetime.now(timezone.utc)
_LIFECYCLE_STARTED_AT: datetime | None = None


def mark_lifecycle_started() -> None:
    """application_lifecycle.startup 성공 시 호출."""

    global _LIFECYCLE_STARTED_AT
    _LIFECYCLE_STARTED_AT = datetime.now(timezone.utc)


def get_process_started_at() -> datetime:
    return _LIFECYCLE_STARTED_AT or _PROCESS_STARTED_AT


def get_uptime_seconds() -> float:
    return max(0.0, time.monotonic() - _MODULE_STARTED_MONOTONIC)


@lru_cache(maxsize=1)
def resolve_git_commit() -> str | None:
    """가능하면 짧은 git SHA. 실패 시 None (예외 삼킴)."""

    env_commit = (
        os.environ.get("GIT_COMMIT")
        or os.environ.get("GITHUB_SHA")
        or ""
    ).strip()
    if env_commit:
        return env_commit[:12]

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if result.returncode == 0:
            value = (result.stdout or "").strip()
            return value or None
    except Exception:
        return None
    return None


def build_system_identity() -> dict[str, Any]:
    settings = get_settings()
    started = get_process_started_at()
    return {
        "status": "UP",
        "server_status": "UP",
        "uptime_seconds": round(get_uptime_seconds(), 1),
        "started_at": started.isoformat(),
        "environment": settings.app_env,
        "app_name": settings.app_name,
        "version": settings.app_version,
        "build_version": (
            os.environ.get("BUILD_VERSION")
            or settings.app_version
        ),
        "git_commit": resolve_git_commit(),
        "timezone": settings.app_timezone,
    }
