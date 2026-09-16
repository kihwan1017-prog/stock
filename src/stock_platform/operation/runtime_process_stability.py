"""REAL 자동매매 런타임 ↔ 개발 hot-reload 분리.

History #92: PROCESS_HOT_RELOAD_FAIL_CLOSED 재발 방지.
매매 정책/restore gate 변경 없음 — 프로세스 안정성 가드만.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from stock_platform.common.settings import is_testing_runtime

RuntimeMode = Literal["development", "production"]

CODE_REAL_RUNTIME_REQUIRES_STABLE_PROCESS = (
    "REAL_RUNTIME_REQUIRES_STABLE_PROCESS"
)
MSG_REAL_RUNTIME_REQUIRES_STABLE_PROCESS_KO = (
    "실거래 자동매매는 개발 자동 재시작 모드에서 실행할 수 없습니다."
)

# fail_closed_restart 원인 분류 (사후 분석용)
RESTART_CAUSE_CONTROLLED = "CONTROLLED_RESTART"
RESTART_CAUSE_DEV_HOT_RELOAD = "DEV_HOT_RELOAD"
RESTART_CAUSE_PROCESS_CRASH = "PROCESS_CRASH"
RESTART_CAUSE_UNKNOWN = "UNKNOWN"


class RealRuntimeUnstableError(RuntimeError):
    """hot-reload/dev 프로세스에서 REAL activation 시도 시 fail-closed."""

    def __init__(
        self,
        code: str = CODE_REAL_RUNTIME_REQUIRES_STABLE_PROCESS,
        message: str = MSG_REAL_RUNTIME_REQUIRES_STABLE_PROCESS_KO,
    ) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _truthy(raw: str | None) -> bool | None:
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def resolve_runtime_mode() -> RuntimeMode:
    """APP_RUNTIME_MODE 우선, 없으면 STOCK_PLATFORM_LAUNCH_MODE 호환."""

    explicit = (os.environ.get("APP_RUNTIME_MODE") or "").strip().lower()
    if explicit in {"production", "prod"}:
        return "production"
    if explicit in {"development", "dev"}:
        return "development"

    launch = (os.environ.get("STOCK_PLATFORM_LAUNCH_MODE") or "").strip().upper()
    if launch in {"PROD", "PRODUCTION"}:
        return "production"
    if launch in {"DEV", "DEVELOPMENT"}:
        return "development"

    # 미설정 시 development — REAL activation 가드가 더 엄격해짐
    return "development"


def is_hot_reload_enabled() -> bool:
    """스크립트가 HOT_RELOAD_ENABLED 를 명시하면 그것을 SoT로 사용."""

    explicit = _truthy(os.environ.get("HOT_RELOAD_ENABLED"))
    if explicit is not None:
        return bool(explicit)
    # production 런처/NSSM 은 reload 없음
    return resolve_runtime_mode() == "development"


def is_stable_runtime() -> bool:
    """production + reload OFF = REAL 자동매매에 적합한 안정 프로세스."""

    return resolve_runtime_mode() == "production" and not is_hot_reload_enabled()


def requires_stable_runtime() -> bool:
    """REAL 활성 시 안정 프로세스가 필요한지 (관측용)."""

    return True


def assert_stable_runtime_for_real_trading(*, context: str = "") -> None:
    """REAL LIVE/ARM/restore 활성화 직전 호출. testing runtime 은 통과."""

    if is_testing_runtime():
        return
    if is_stable_runtime():
        return
    detail = (
        f"{MSG_REAL_RUNTIME_REQUIRES_STABLE_PROCESS_KO}"
        f" (mode={resolve_runtime_mode()},"
        f" hot_reload={is_hot_reload_enabled()}"
        f"{f', context={context}' if context else ''})"
    )
    raise RealRuntimeUnstableError(
        CODE_REAL_RUNTIME_REQUIRES_STABLE_PROCESS,
        detail,
    )


def classify_startup_fail_closed_cause() -> str:
    """startup fail_closed_restart 원인 추정."""

    if is_hot_reload_enabled() or resolve_runtime_mode() == "development":
        return RESTART_CAUSE_DEV_HOT_RELOAD
    controlled = _truthy(os.environ.get("STOCK_PLATFORM_CONTROLLED_RESTART"))
    if controlled is True:
        return RESTART_CAUSE_CONTROLLED
    return RESTART_CAUSE_UNKNOWN


def build_runtime_stability_snapshot() -> dict[str, Any]:
    """ops-status / PROCESS_START audit 용."""

    mode = resolve_runtime_mode()
    hot_reload = is_hot_reload_enabled()
    stable = is_stable_runtime()
    return {
        "RUNTIME_MODE": mode,
        "HOT_RELOAD_ENABLED": hot_reload,
        "STABLE_RUNTIME_REQUIRED": True,
        "REAL_RUNTIME_STABLE": stable,
        "APP_RUNTIME_MODE": mode,
        "STOCK_PLATFORM_LAUNCH_MODE": (
            os.environ.get("STOCK_PLATFORM_LAUNCH_MODE") or ""
        ).strip()
        or None,
        "pid": os.getpid(),
        "reload_watch_hint": (
            "src only (--reload-dir src); frontend excluded"
            if hot_reload
            else "none"
        ),
    }


def real_runtime_unstable_health_reason(
    *,
    live_on: bool,
    arm_on: bool,
    lease_active: bool = False,
) -> str | None:
    """REAL 지표가 켜져 있는데 hot-reload 프로세스면 health reason."""

    if is_testing_runtime():
        return None
    if is_stable_runtime():
        return None
    if live_on or arm_on or lease_active:
        return "REAL_RUNTIME_UNSTABLE_DEV_RELOAD"
    return None
