"""STEP 8-5-21 — LIVE 환경값 불일치·Activation Gate 점검."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings


@dataclass
class LiveConfigGateResult:
    allowed: bool
    status: str  # HEALTHY | DEGRADED | CRITICAL
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


def evaluate_live_flag_consistency() -> LiveConfigGateResult:
    """환경 플래그 조합 검증 (주문 전 Fail Closed용)."""

    s = get_settings()
    detail = {
        "global_live_order_enabled": s.global_live_order_enabled,
        "kiwoom_live_order_enabled": s.kiwoom_live_order_enabled,
        "upbit_live_order_enabled": s.upbit_live_order_enabled,
        "kiwoom_use_mock": s.kiwoom_use_mock,
    }

    # Case 3: GLOBAL+Kiwoom LIVE + Mock → 실계좌 금지
    if (
        s.global_live_order_enabled
        and s.kiwoom_live_order_enabled
        and s.kiwoom_use_mock
    ):
        return LiveConfigGateResult(
            allowed=False,
            status="CRITICAL",
            code="LIVE_MOCK_CONFLICT",
            message=(
                "GLOBAL+KIWOOM LIVE with KIWOOM_USE_MOCK=true — "
                "real account orders forbidden"
            ),
            detail=detail,
        )

    # Case 1: GLOBAL OFF + Kiwoom LIVE ON → 불일치
    if (not s.global_live_order_enabled) and s.kiwoom_live_order_enabled:
        return LiveConfigGateResult(
            allowed=False,
            status="DEGRADED",
            code="LIVE_FLAG_MISMATCH_KIWOOM",
            message=(
                "KIWOOM_LIVE_ORDER_ENABLED=true but "
                "GLOBAL_LIVE_ORDER_ENABLED=false — orders blocked"
            ),
            detail=detail,
        )

    # Case 2: GLOBAL ON + Kiwoom OFF → 키움 LIVE 차단 (업비트만 가능)
    if s.global_live_order_enabled and not s.kiwoom_live_order_enabled:
        return LiveConfigGateResult(
            allowed=True,
            status="HEALTHY",
            code="KIWOOM_LIVE_OFF",
            message="Kiwoom LIVE disabled; Kiwoom live orders blocked",
            detail={**detail, "kiwoom_live_orders_allowed": False},
        )

    # Case 4: GLOBAL+Kiwoom LIVE+Mock OFF — Activation Gate 필수
    if (
        s.global_live_order_enabled
        and s.kiwoom_live_order_enabled
        and not s.kiwoom_use_mock
    ):
        return LiveConfigGateResult(
            allowed=True,
            status="HEALTHY",
            code="ACTIVATION_GATE_REQUIRED",
            message=(
                "Env flags allow LIVE path only with active "
                "non-expired Activation Gate"
            ),
            detail={**detail, "activation_gate_required": True},
        )

    return LiveConfigGateResult(
        allowed=True,
        status="HEALTHY",
        code="LIVE_SAFE_DEFAULTS",
        message="LIVE flags in RC-safe defaults",
        detail=detail,
    )


def assert_kiwoom_live_env_allows_orders() -> None:
    """키움 LIVE 주문 직전 — 불일치면 PermissionError."""

    result = evaluate_live_flag_consistency()
    if result.code in {
        "LIVE_MOCK_CONFLICT",
        "LIVE_FLAG_MISMATCH_KIWOOM",
    }:
        raise PermissionError(f"{result.code}: {result.message}")
    if result.code == "KIWOOM_LIVE_OFF":
        raise PermissionError(
            "KIWOOM_LIVE_ORDER_ENABLED must be true for Kiwoom LIVE"
        )
    s = get_settings()
    if not s.global_live_order_enabled:
        raise PermissionError("GLOBAL_LIVE_ORDER_ENABLED must be true")
    if s.kiwoom_use_mock:
        raise PermissionError("KIWOOM_USE_MOCK must be false for live orders")


def record_live_config_audit(
    session: Session,
    *,
    actor: str,
    result: LiveConfigGateResult,
) -> None:
    """가능하면 Audit 기록 (실패해도 주문 차단은 유지)."""

    try:
        from stock_platform.api.deps_admin import AuditLogService

        AuditLogService(session).record(
            event_type="LIVE_CONFIG_GATE",
            actor=actor,
            detail={
                "code": result.code,
                "status": result.status,
                "allowed": result.allowed,
                "message": result.message,
                "flags": result.detail,
            },
        )
        session.commit()
    except Exception:  # noqa: BLE001
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
