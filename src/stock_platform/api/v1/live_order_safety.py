"""STEP 8-7 — Admin/User LIVE 주문 승인·상태 API."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.account_ownership import (
    assert_broker_account_access,
)
from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.risk_engine.user_risk_service import (
    RiskSettingValidationError,
    UserRiskSettingService,
)
from stock_platform.trading.live_order_approval_service import (
    LiveOrderApprovalError,
    LiveOrderApprovalService,
)

admin_router = APIRouter(
    prefix="/api/v1/admin/live-order",
    tags=["Admin Live Order Safety"],
    dependencies=[Depends(require_admin)],
)

user_router = APIRouter(
    prefix="/api/v1/user/live-order",
    tags=["User Live Order Safety"],
)


class LiveToggleRequest(BaseModel):
    """LIVE 플래그만 변경. ARM·Scheduler·Runtime은 이 API로 변경하지 않는다."""

    live_order_enabled: bool
    # Enable 시 필수 (서비스에서 재검증)
    reason: str | None = Field(default=None, max_length=2000)
    correlation_id: str | None = Field(default=None, max_length=128)


class AccountRiskLimitsRequest(BaseModel):
    max_order_amount: Decimal | None = Field(default=None, ge=0)
    max_order_quantity: Decimal | None = Field(default=None, ge=0)
    daily_order_limit: int | None = Field(default=None, ge=0)
    daily_max_loss_amount: Decimal | None = Field(default=None, ge=0)
    duplicate_order_window_seconds: int | None = Field(
        default=None, ge=0, le=3600
    )
    max_open_orders: int | None = Field(default=None, ge=0)
    max_slippage_rate: Decimal | None = Field(default=None, ge=0, le=1)
    anomaly_orders_per_minute: int | None = Field(default=None, ge=0)
    arm_ttl_seconds: int | None = Field(default=None, ge=1, le=3600)


class ArmRequest(BaseModel):
    """ARM만 ON. LIVE·Scheduler·Runtime은 변경하지 않는다."""

    ttl_seconds: int | None = Field(default=None, ge=1, le=3600)
    reason: str | None = Field(default=None, max_length=2000)
    correlation_id: str | None = Field(default=None, max_length=128)


class DisarmRequest(BaseModel):
    """ARM OFF 비상 경로. 기본은 LIVE 유지."""

    turn_live_off: bool = False
    reason: str = Field(min_length=1, max_length=2000)
    correlation_id: str | None = Field(default=None, max_length=128)


@admin_router.get("/accounts/{user_broker_account_id}")
def admin_get_live_status(
    user_broker_account_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    assert_broker_account_access(
        user, user_broker_account_id, session
    )
    try:
        return LiveOrderApprovalService(session).get_status(
            user_broker_account_id
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@admin_router.put("/accounts/{user_broker_account_id}")
def admin_set_live_enabled(
    user_broker_account_id: int,
    body: LiveToggleRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """LIVE ON/OFF만 수행. ARM/Scheduler/Runtime/주문은 변경·생성하지 않는다."""
    assert_broker_account_access(
        user, user_broker_account_id, session
    )
    service = LiveOrderApprovalService(session)
    try:
        result = service.set_live_enabled(
            user_broker_account_id,
            enabled=body.live_order_enabled,
            actor=user.username,
            reason=body.reason,
            correlation_id=body.correlation_id,
            run_id=(
                body.correlation_id
                or getattr(http_request.state, "request_id", None)
            ),
        )
        session.commit()
    except LookupError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except LiveOrderApprovalError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    # already_enabled 이면 중복 Audit 생략
    if result.get("already_enabled"):
        return result
    if not result.get("live_changed", True) and body.live_order_enabled:
        return result
    audit.record(
        event_type=(
            "LIVE_APPROVED"
            if body.live_order_enabled
            else "LIVE_DISABLED"
        ),
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "user_broker_account_id": user_broker_account_id,
            "user_id": result.get("user_id"),
            "broker_code": result.get("broker_code"),
            "live_order_enabled": body.live_order_enabled,
            "previous_live": result.get("previous_live"),
            "new_live": body.live_order_enabled,
            "arm": result.get("live_armed"),
            "reason": body.reason,
            "correlation_id": body.correlation_id,
            "actor_role": "ADMIN",
        },
    )
    session.commit()
    return result


@admin_router.put("/accounts/{user_broker_account_id}/risk-limits")
def admin_put_live_risk_limits(
    user_broker_account_id: int,
    body: AccountRiskLimitsRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    uba = assert_broker_account_access(
        user, user_broker_account_id, session
    )
    service = UserRiskSettingService(session)
    payload = body.model_dump(exclude_unset=True)
    try:
        service.upsert_account(
            user_broker_account_id, payload, actor=user.username
        )
        session.commit()
    except RiskSettingValidationError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    audit.record(
        event_type="ADMIN_LIVE_RISK_LIMITS_UPDATE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "user_broker_account_id": user_broker_account_id,
            "user_id": int(uba.user_id),
            "payload": {k: str(v) for k, v in payload.items()},
        },
    )
    session.commit()
    return LiveOrderApprovalService(session).get_status(
        user_broker_account_id
    )


@admin_router.get("/users/{user_id}/accounts")
def admin_list_user_live_accounts(
    user_id: int,
    session: Session = Depends(get_db_session),
):
    return {
        "user_id": user_id,
        "accounts": LiveOrderApprovalService(session).list_for_user(
            user_id
        ),
    }


@admin_router.post("/accounts/{user_broker_account_id}/arm")
def admin_arm_live(
    user_broker_account_id: int,
    body: ArmRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """STEP 8-8/9-4 — LIVE ARM (관리자 전용). Scheduler/Runtime 미변경.
    arm_token은 응답에만 1회 포함 (Audit/로그 금지).
    """

    assert_broker_account_access(user, user_broker_account_id, session)
    from stock_platform.trading.live_arm_service import (
        LiveArmError,
        LiveArmService,
    )

    try:
        result = LiveArmService(session).arm(
            user_broker_account_id,
            actor=user.username,
            ttl_seconds=body.ttl_seconds,
            reason=body.reason,
            correlation_id=body.correlation_id,
            run_id=(
                body.correlation_id
                or getattr(http_request.state, "request_id", None)
            ),
            enforce_gates=True,
        )
        session.commit()
    except LiveArmError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except LookupError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    if result.get("already_armed"):
        return result

    # Audit에는 arm_token 원문 절대 미포함
    audit_safe = {
        k: v
        for k, v in result.items()
        if k != "arm_token"
    }
    audit.record(
        event_type="LIVE_ARM",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "user_broker_account_id": user_broker_account_id,
            "user_id": audit_safe.get("user_id"),
            "broker_code": audit_safe.get("broker_code"),
            "previous_arm": result.get("previous_arm"),
            "new_arm": True,
            "live": audit_safe.get("live_order_enabled"),
            "live_order_enabled": audit_safe.get("live_order_enabled"),
            "arm_expires_at": audit_safe.get("arm_expires_at"),
            "reason": body.reason,
            "correlation_id": body.correlation_id,
            "actor_role": "ADMIN",
            "trading_scheduler": "PAUSED",
            "runtime": "paused",
        },
    )
    session.commit()
    return result


@admin_router.post("/accounts/{user_broker_account_id}/disarm")
def admin_disarm_live(
    user_broker_account_id: int,
    body: DisarmRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """ARM Disable 비상 경로. 기본 turn_live_off=False → LIVE 유지."""
    assert_broker_account_access(user, user_broker_account_id, session)
    from stock_platform.trading.live_arm_service import (
        LiveArmError,
        LiveArmService,
    )

    try:
        result = LiveArmService(session).disarm(
            user_broker_account_id,
            actor=user.username,
            reason=body.reason,
            turn_live_off=body.turn_live_off,
            correlation_id=body.correlation_id,
            run_id=(
                body.correlation_id
                or getattr(http_request.state, "request_id", None)
            ),
            require_correlation_id=True,
        )
        session.commit()
    except LiveArmError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except LookupError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    audit.record(
        event_type="LIVE_DISARM",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "user_broker_account_id": user_broker_account_id,
            "reason": body.reason,
            "correlation_id": body.correlation_id,
            "turn_live_off": body.turn_live_off,
            "live": result.get("live_order_enabled"),
            "previous_arm": result.get("previous_arm"),
            "new_arm": False,
            "actor_role": "ADMIN",
        },
    )
    session.commit()
    return result


@admin_router.get("/accounts/{user_broker_account_id}/arm")
def admin_get_arm_status(
    user_broker_account_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    assert_broker_account_access(user, user_broker_account_id, session)
    from stock_platform.trading.live_arm_service import LiveArmService

    try:
        return LiveArmService(session).get_arm_status(user_broker_account_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@admin_router.get("/dashboard")
def admin_live_ops_dashboard(
    session: Session = Depends(get_db_session),
):
    """STEP 8-8 — LIVE/ARM/Kill/Broker/Scheduler/Orders 요약."""

    from stock_platform.trading.live_ops_dashboard import (
        LiveOpsDashboardService,
    )

    return LiveOpsDashboardService(session).snapshot()


@admin_router.get("/orders/{order_id}/post-fill")
def admin_get_order_post_fill(
    order_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    """STEP 10-1 — 주문별 Post-fill / Snapshot 상태 조회."""

    from sqlalchemy import select

    from stock_platform.order.entities import TradingOrderEntity
    from stock_platform.order.post_fill_verification_entities import (
        PostFillVerificationEntity,
    )

    order = session.get(TradingOrderEntity, int(order_id))
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ORDER_NOT_FOUND"
        )
    if order.user_broker_account_id is not None:
        assert_broker_account_access(
            user, int(order.user_broker_account_id), session
        )
    rows = list(
        session.scalars(
            select(PostFillVerificationEntity)
            .where(PostFillVerificationEntity.order_id == int(order_id))
            .order_by(PostFillVerificationEntity.verification_id.desc())
        )
    )
    return {
        "order_id": int(order_id),
        "order_status": order.status_code,
        "broker_order_id": order.broker_order_id,
        "filled_quantity": str(order.filled_quantity),
        "average_fill_price": (
            None
            if order.average_fill_price is None
            else str(order.average_fill_price)
        ),
        "post_fill": [
            {
                "verification_id": r.verification_id,
                "status_code": r.status_code,
                "retry_count": r.retry_count,
                "last_error_code": r.last_error_code,
                "created_at": r.created_at,
                "verified_at": r.verified_at,
            }
            for r in rows
        ],
    }


@admin_router.post("/orders/{order_id}/fill-sync")
def admin_order_fill_sync(
    order_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """STEP 10-1 — 주문 체결 동기화 + Post-fill (실주문 제출 없음)."""

    from stock_platform.broker.upbit.fill_sync_service import (
        UpbitFillSyncService,
    )
    from stock_platform.order.entities import TradingOrderEntity

    order = session.get(TradingOrderEntity, int(order_id))
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ORDER_NOT_FOUND"
        )
    if order.user_broker_account_id is not None:
        assert_broker_account_access(
            user, int(order.user_broker_account_id), session
        )
    try:
        result = UpbitFillSyncService(session).sync_by_order_id(
            int(order_id),
            actor=user.username,
        )
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{type(exc).__name__}:{exc}",
        ) from exc
    audit.record(
        event_type="ADMIN_ORDER_FILL_SYNC",
        actor=user.username,
        detail={
            "order_id": int(order_id),
            "order_status": result.order_status,
            "new_executions": result.new_executions,
            "post_fill_enqueued": result.post_fill_enqueued,
            "already_processed": result.already_processed,
        },
    )
    session.commit()
    return {
        "order_id": result.order_id,
        "order_status": result.order_status,
        "new_executions": result.new_executions,
        "duplicate_executions": result.duplicate_executions,
        "post_fill_enqueued": result.post_fill_enqueued,
        "already_processed": result.already_processed,
        "detail": result.detail,
    }


@admin_router.post("/orders/{order_id}/post-fill/retry")
def admin_retry_order_post_fill(
    order_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """STEP 10-1 — 실패/대기 Post-fill 수동 재처리 (주문 재제출 금지)."""

    from stock_platform.order.entities import TradingOrderEntity
    from stock_platform.order.post_fill_runner import PostFillVerifyRunner

    order = session.get(TradingOrderEntity, int(order_id))
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ORDER_NOT_FOUND"
        )
    if order.user_broker_account_id is not None:
        assert_broker_account_access(
            user, int(order.user_broker_account_id), session
        )
    result = PostFillVerifyRunner(session).verify_after_order_fill(
        order=order,
        execution_id=None,
        actor=user.username,
    )
    session.commit()
    audit.record(
        event_type="ADMIN_POST_FILL_RETRY",
        actor=user.username,
        detail={
            "order_id": int(order_id),
            "ok": result.ok,
            "reason_code": result.reason_code,
        },
    )
    session.commit()
    return {
        "order_id": int(order_id),
        "ok": result.ok,
        "reason_code": result.reason_code,
        "detail": result.detail,
    }


@admin_router.post("/broker-disconnect/{broker_code}")
def admin_simulate_broker_disconnect(
    broker_code: str,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    """운영 보호 테스트용 — 실주문 없이 Broker Down 연쇄."""

    from stock_platform.trading.broker_disconnect_protector import (
        BrokerDisconnectProtector,
    )

    result = BrokerDisconnectProtector(session).on_broker_down(
        broker_code=broker_code,
        actor=user.username,
    )
    session.commit()
    return result


@user_router.get("/accounts")
def user_list_live_status(
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    return {
        "user_id": int(user.user_id),
        "accounts": LiveOrderApprovalService(session).list_for_user(
            int(user.user_id)
        ),
    }


@user_router.get("/accounts/{user_broker_account_id}")
def user_get_live_status(
    user_broker_account_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    assert_broker_account_access(
        user, user_broker_account_id, session
    )
    try:
        return LiveOrderApprovalService(session).get_status(
            user_broker_account_id
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@user_router.get("/dashboard")
def user_live_ops_dashboard_readonly(
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """사용자 읽기 전용 — 본인 계좌 LIVE/ARM/Post-Fill 요약만."""

    from stock_platform.order.post_fill_verification_service import (
        PostFillVerificationService,
    )
    from stock_platform.trading.live_arm_service import LiveArmService

    accounts = LiveOrderApprovalService(session).list_for_user(
        int(user.user_id)
    )
    arm = LiveArmService(session)
    arm_rows = [
        arm.get_arm_status(int(a["user_broker_account_id"]))
        for a in accounts
    ]
    uba_ids = [int(a["user_broker_account_id"]) for a in accounts]
    return {
        "user_id": int(user.user_id),
        "accounts": arm_rows,
        "post_fill_verification": PostFillVerificationService(
            session
        ).dashboard_counts(user_broker_account_ids=uba_ids),
        "readonly": True,
    }
