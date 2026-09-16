"""System Health 리허설 — 필수/선택 컴포넌트 판정."""

from __future__ import annotations

import asyncio
from typing import Any

from stock_platform.common.settings import get_settings
from stock_platform.operation.health_service import (
    SystemHealthService,
    check_database,
    check_ollama,
)
from stock_platform.operations.rehearsal.checks import run_check
from stock_platform.operations.rehearsal.models import (
    CheckResult,
    CheckStatus,
)

# 필수: 장애 시 aggregate FAIL
REQUIRED_COMPONENTS = frozenset({"database", "scheduler", "backend_api"})

# 선택: 의도적 DISABLED → NOT_APPLICABLE, DEGRADED → WARNING, DOWN → WARNING
OPTIONAL_COMPONENTS = frozenset(
    {"ollama", "telegram", "live_trading", "kiwoom_rest", "upbit_rest"}
)


def classify_component(
    name: str,
    raw: dict[str, Any],
    *,
    settings: Any | None = None,
) -> tuple[CheckStatus, str]:
    """컴포넌트 원시 상태를 CheckStatus로 변환."""

    settings = settings or get_settings()
    value = str(raw.get("status") or "").upper()
    required = name in REQUIRED_COMPONENTS

    if name == "live_trading":
        # RC/Paper: LIVE OFF는 정상 (의도적 비활성)
        if value in {"DISABLED", "OFF", "FALSE"} or not bool(
            raw.get("live_order_enabled", False)
        ):
            return (
                CheckStatus.NOT_APPLICABLE,
                "live trading intentionally disabled",
            )
        if value in {"ENABLED", "UP", "OK"}:
            return CheckStatus.PASS, "live trading enabled"
        return CheckStatus.FAIL, f"unexpected live_trading status={value}"

    if name == "telegram":
        enabled = bool(
            getattr(settings, "telegram_enabled", False)
            or getattr(settings, "telegram_ops_enabled", False)
        )
        if not enabled:
            return (
                CheckStatus.NOT_APPLICABLE,
                "telegram intentionally disabled",
            )
        return CheckStatus.PASS, "telegram enabled"

    if name == "scheduler":
        enabled = bool(getattr(settings, "scheduler_enabled", False))
        if not enabled:
            return (
                CheckStatus.NOT_APPLICABLE,
                "scheduler intentionally disabled",
            )
        if value in {"UP", "OK", "ENABLED", "CONFIGURED"}:
            return CheckStatus.PASS, "scheduler up"
        if value == "DEGRADED":
            return CheckStatus.FAIL, "scheduler degraded (required)"
        if value == "DISABLED":
            # 설정은 enabled인데 상태가 DISABLED → 불일치
            return CheckStatus.FAIL, "scheduler disabled while enabled in settings"
        return CheckStatus.FAIL, f"scheduler status={value}"

    if name == "database":
        if value == "UP":
            return CheckStatus.PASS, "database up"
        return CheckStatus.FAIL, f"database status={value}"

    if value in {"UP", "OK", "HEALTHY", "CONFIGURED", "ENABLED"}:
        return CheckStatus.PASS, f"{name} ok"

    if value == "DEGRADED":
        if required:
            return CheckStatus.FAIL, f"{name} degraded (required)"
        return CheckStatus.WARNING, f"{name} degraded (optional)"

    if value in {"DISABLED", "SKIPPED"}:
        if required:
            return CheckStatus.FAIL, f"{name} disabled (required)"
        return (
            CheckStatus.NOT_APPLICABLE,
            f"{name} intentionally disabled/skipped",
        )

    if value in {"DOWN", "CRITICAL", "ERROR"}:
        if required:
            return CheckStatus.FAIL, f"{name} down (required)"
        return CheckStatus.WARNING, f"{name} down (optional)"

    if required:
        return CheckStatus.FAIL, f"{name} unknown status={value}"
    return CheckStatus.WARNING, f"{name} unknown status={value}"


def _worst(statuses: list[CheckStatus]) -> CheckStatus:
    if CheckStatus.FAIL in statuses:
        return CheckStatus.FAIL
    if CheckStatus.WARNING in statuses:
        return CheckStatus.WARNING
    if CheckStatus.PASS in statuses:
        return CheckStatus.PASS
    if CheckStatus.NOT_APPLICABLE in statuses:
        return CheckStatus.NOT_APPLICABLE
    return CheckStatus.SKIPPED


def run_health_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    settings = get_settings()

    def _db() -> tuple[CheckStatus, str, dict[str, Any]]:
        payload = check_database()
        status, message = classify_component("database", payload, settings=settings)
        return status, message, payload

    results.append(run_check(suite="health", name="postgresql", fn=_db))

    def _ollama() -> tuple[CheckStatus, str, dict[str, Any]]:
        payload = check_ollama()
        status, message = classify_component("ollama", payload, settings=settings)
        return status, message, payload

    results.append(run_check(suite="health", name="ollama", fn=_ollama))

    def _aggregate() -> tuple[CheckStatus, str, dict[str, Any]]:
        payload = asyncio.run(SystemHealthService().build())
        components = payload.get("components") or {}
        mapped: dict[str, dict[str, Any]] = {}
        statuses: list[CheckStatus] = []

        for key in (
            "database",
            "scheduler",
            "kiwoom_rest",
            "upbit_rest",
            "ollama",
            "live_trading",
        ):
            comp = components.get(key) or {}
            if not isinstance(comp, dict):
                comp = {"status": str(comp)}
            st, reason = classify_component(key, comp, settings=settings)
            mapped[key] = {
                "status": str(st),
                "raw": str(comp.get("status")),
                "required": key in REQUIRED_COMPONENTS,
                "reason": reason,
            }
            statuses.append(st)

        tg_raw = {
            "status": (
                "ENABLED"
                if (
                    settings.telegram_enabled or settings.telegram_ops_enabled
                )
                else "DISABLED"
            )
        }
        tg_st, tg_reason = classify_component(
            "telegram", tg_raw, settings=settings
        )
        mapped["telegram"] = {
            "status": str(tg_st),
            "raw": tg_raw["status"],
            "required": False,
            "reason": tg_reason,
        }
        statuses.append(tg_st)

        worst = _worst(statuses)
        warn_or_fail = [
            k
            for k, v in mapped.items()
            if v["status"] in {CheckStatus.WARNING, CheckStatus.FAIL}
        ]
        message = (
            f"worst={worst}; notable={warn_or_fail or ['none']}"
        )
        return worst, message, {"components": mapped}

    results.append(
        run_check(suite="health", name="system_health_aggregate", fn=_aggregate)
    )

    def _api_surface() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.api.v1 import health as health_api

        assert hasattr(health_api, "health_live")
        assert hasattr(health_api, "health_ready")
        return CheckStatus.PASS, "health routes importable", {"required": True}

    results.append(run_check(suite="health", name="backend_api", fn=_api_surface))
    return results
