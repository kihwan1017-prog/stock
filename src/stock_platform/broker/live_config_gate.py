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


def evaluate_live_flag_consistency(
    broker_code: str | None = None,
    *,
    session: Session | None = None,
    user_broker_account_id: int | None = None,
    uses_system_shared_credential: bool = False,
    credential_ref: str | None = None,
) -> LiveConfigGateResult:
    """환경 플래그 조합 검증 (주문 전 Fail Closed용).

    broker_code=UPBIT 이면 KIWOOM mock/live conflict를 적용하지 않는다.
    broker_code=KIWOOM 또는 None(전역 점검)은 기존 KIWOOM 계약을 유지한다.
    UBA explicit REAL credential 이면 LIVE_MOCK_CONFLICT 대신
    KIWOOM_EXPLICIT_REAL_EXECUTION (DEGRADED) 을 반환한다.
    LIVE_MOCK_CONFLICT 자체를 전역 비활성화하지 않는다.
    """

    s = get_settings()
    broker = str(broker_code or "").strip().upper() or None
    detail = {
        "global_live_order_enabled": s.global_live_order_enabled,
        "kiwoom_live_order_enabled": s.kiwoom_live_order_enabled,
        "upbit_live_order_enabled": s.upbit_live_order_enabled,
        "kiwoom_use_mock": s.kiwoom_use_mock,
        "upbit_use_mock": s.upbit_use_mock,
        "broker_code": broker,
    }

    # UPBIT 주문은 UPBIT 플래그만 본다 (cross-broker contamination 방지)
    if broker == "UPBIT":
        if not s.global_live_order_enabled:
            return LiveConfigGateResult(
                allowed=False,
                status="CRITICAL",
                code="GLOBAL_LIVE_OFF",
                message="GLOBAL_LIVE_ORDER_ENABLED=false — UPBIT live blocked",
                detail=detail,
            )
        if not s.upbit_live_order_enabled:
            return LiveConfigGateResult(
                allowed=False,
                status="CRITICAL",
                code="UPBIT_LIVE_OFF",
                message="UPBIT_LIVE_ORDER_ENABLED=false — UPBIT live blocked",
                detail=detail,
            )
        if s.upbit_use_mock:
            return LiveConfigGateResult(
                allowed=False,
                status="CRITICAL",
                code="UPBIT_MOCK_LIVE_CONFLICT",
                message=(
                    "UPBIT_USE_MOCK=true — UPBIT live dispatch forbidden"
                ),
                detail=detail,
            )
        return LiveConfigGateResult(
            allowed=True,
            status="HEALTHY",
            code="UPBIT_FLAGS_OK",
            message=(
                "UPBIT live flags consistent; KIWOOM mock/live ignored"
            ),
            detail={**detail, "kiwoom_flags_ignored": True},
        )

    # Case 3: GLOBAL+Kiwoom LIVE + Mock → 기본 실계좌 금지
    # UBA explicit REAL 이면 실행 SoT를 credential 로 승격 (Option D)
    if (
        s.global_live_order_enabled
        and s.kiwoom_live_order_enabled
        and s.kiwoom_use_mock
    ):
        from stock_platform.broker.kiwoom.execution_env import (
            kiwoom_global_mock_blocks_live_execution,
            kiwoom_market_env_is_mock,
        )

        if not kiwoom_global_mock_blocks_live_execution(
            session,
            user_broker_account_id=user_broker_account_id,
            uses_system_shared_credential=uses_system_shared_credential,
            credential_ref=credential_ref,
        ) and user_broker_account_id is not None:
            return LiveConfigGateResult(
                allowed=True,
                status="DEGRADED",
                code="KIWOOM_EXPLICIT_REAL_EXECUTION",
                message=(
                    "UBA explicit REAL execution; "
                    "KIWOOM_USE_MOCK is market/WS only"
                ),
                detail={
                    **detail,
                    "execution_env": "REAL",
                    "market_env": (
                        "MOCK" if kiwoom_market_env_is_mock() else "REAL"
                    ),
                    "user_broker_account_id": int(user_broker_account_id),
                },
            )
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


def assert_kiwoom_live_env_allows_orders(
    session: Session | None = None,
    *,
    user_broker_account_id: int | None = None,
    uses_system_shared_credential: bool = False,
    credential_ref: str | None = None,
) -> None:
    """키움 LIVE 주문 직전 — 불일치면 PermissionError.

    UBA + explicit REAL credential 이면 global kiwoom_use_mock 로 차단하지 않는다.
    """

    from stock_platform.broker.kiwoom.execution_env import (
        kiwoom_global_mock_blocks_live_execution,
    )

    result = evaluate_live_flag_consistency(
        broker_code="KIWOOM",
        session=session,
        user_broker_account_id=user_broker_account_id,
        uses_system_shared_credential=uses_system_shared_credential,
        credential_ref=credential_ref,
    )
    if result.code == "LIVE_FLAG_MISMATCH_KIWOOM":
        raise PermissionError(f"{result.code}: {result.message}")
    if result.code == "LIVE_MOCK_CONFLICT":
        if kiwoom_global_mock_blocks_live_execution(
            session,
            user_broker_account_id=user_broker_account_id,
            uses_system_shared_credential=uses_system_shared_credential,
            credential_ref=credential_ref,
        ):
            raise PermissionError(f"{result.code}: {result.message}")
    if result.code == "KIWOOM_LIVE_OFF":
        raise PermissionError(
            "KIWOOM_LIVE_ORDER_ENABLED must be true for Kiwoom LIVE"
        )
    s = get_settings()
    if not s.global_live_order_enabled:
        raise PermissionError("GLOBAL_LIVE_ORDER_ENABLED must be true")
    if kiwoom_global_mock_blocks_live_execution(
        session,
        user_broker_account_id=user_broker_account_id,
        uses_system_shared_credential=uses_system_shared_credential,
        credential_ref=credential_ref,
    ):
        raise PermissionError(
            "Kiwoom LIVE execution blocked: unresolved mock environment"
        )


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
