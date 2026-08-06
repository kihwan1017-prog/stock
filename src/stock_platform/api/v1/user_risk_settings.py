from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import AuditLogService, get_audit_service
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


router = APIRouter(
    prefix="/api/v1/user",
    tags=["User Risk Settings"],
)


class RiskSettingUpdateRequest(BaseModel):
    max_order_amount: Decimal | None = Field(default=None, ge=0)
    daily_max_order_amount: Decimal | None = Field(default=None, ge=0)
    max_total_investment_amount: Decimal | None = Field(
        default=None, ge=0
    )
    max_position_amount: Decimal | None = Field(default=None, ge=0)
    max_position_count: int | None = Field(default=None, ge=0)
    max_position_weight: Decimal | None = Field(
        default=None, ge=0, le=1
    )
    max_investment_ratio: Decimal | None = Field(
        default=None, ge=0, le=1
    )
    allow_duplicate_buy: bool | None = None
    daily_max_loss_amount: Decimal | None = Field(default=None, ge=0)
    daily_max_loss_rate: Decimal | None = Field(
        default=None, ge=0, le=1
    )
    stop_loss_rate: Decimal | None = Field(default=None, ge=0, le=1)
    take_profit_rate: Decimal | None = Field(default=None, ge=0, le=1)
    trailing_stop_rate: Decimal | None = Field(
        default=None, ge=0, le=1
    )
    auto_trading_enabled: bool | None = None
    buy_enabled: bool | None = None
    sell_enabled: bool | None = None
    sell_only: bool | None = None
    account_paused: bool | None = None
    max_order_quantity: Decimal | None = Field(default=None, ge=0)
    daily_order_limit: int | None = Field(default=None, ge=0)
    duplicate_order_window_seconds: int | None = Field(
        default=None, ge=0, le=3600
    )


def _payload(body: RiskSettingUpdateRequest) -> dict[str, Any]:
    return body.model_dump(exclude_unset=True)


@router.get("/risk-settings")
def get_my_risk_settings(
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    service = UserRiskSettingService(session)
    resolved = service.resolve(user_id=int(user.user_id))
    return {
        "user_id": int(user.user_id),
        "stored": service.snapshot_user(int(user.user_id)),
        "resolved": resolved.as_dict(),
        "paper_note": (
            "Paper 주문은 UserBrokerAccount 설정이 없고 "
            "사용자 기본 + 시스템 기본만 적용됩니다."
        ),
    }


@router.put("/risk-settings")
def put_my_risk_settings(
    body: RiskSettingUpdateRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    service = UserRiskSettingService(session)
    before = service.snapshot_user(int(user.user_id))
    try:
        service.upsert_user(
            int(user.user_id),
            _payload(body),
            actor=user.username,
        )
        session.commit()
    except RiskSettingValidationError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    after = service.snapshot_user(int(user.user_id))
    audit.record(
        event_type="USER_RISK_SETTINGS_UPDATE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "target_user_id": int(user.user_id),
            "before": before,
            "after": after,
        },
    )
    session.commit()
    resolved = service.resolve(user_id=int(user.user_id))
    return {
        "user_id": int(user.user_id),
        "stored": after,
        "resolved": resolved.as_dict(),
    }


@router.get("/accounts/{user_broker_account_id}/risk-settings")
def get_account_risk_settings(
    user_broker_account_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    assert_broker_account_access(
        user, user_broker_account_id, session
    )
    service = UserRiskSettingService(session)
    resolved = service.resolve(
        user_id=int(user.user_id),
        user_broker_account_id=user_broker_account_id,
    )
    return {
        "user_broker_account_id": user_broker_account_id,
        "stored": service.snapshot_account(user_broker_account_id),
        "resolved": resolved.as_dict(),
    }


@router.put("/accounts/{user_broker_account_id}/risk-settings")
def put_account_risk_settings(
    user_broker_account_id: int,
    body: RiskSettingUpdateRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    assert_broker_account_access(
        user, user_broker_account_id, session
    )
    service = UserRiskSettingService(session)
    before = service.snapshot_account(user_broker_account_id)
    try:
        service.upsert_account(
            user_broker_account_id,
            _payload(body),
            actor=user.username,
        )
        session.commit()
    except RiskSettingValidationError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    after = service.snapshot_account(user_broker_account_id)
    audit.record(
        event_type="ACCOUNT_RISK_SETTINGS_UPDATE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "target_user_id": int(user.user_id),
            "user_broker_account_id": user_broker_account_id,
            "before": before,
            "after": after,
        },
    )
    session.commit()
    resolved = service.resolve(
        user_id=int(user.user_id),
        user_broker_account_id=user_broker_account_id,
    )
    return {
        "user_broker_account_id": user_broker_account_id,
        "stored": after,
        "resolved": resolved.as_dict(),
    }
