from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.account_ownership import (
    assert_broker_account_access,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.risk_engine.user_risk_service import (
    RiskSettingValidationError,
    UserRiskSettingService,
)
from stock_platform.trading.account_models import UserBrokerAccount

router = APIRouter(
    prefix="/api/v1/admin/risk-settings",
    tags=["Admin Risk Settings"],
    dependencies=[Depends(require_admin)],
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
    # REAL exit protection tri-state
    stop_loss_mode: str | None = Field(
        default=None, pattern="^(INHERIT|ENABLED|DISABLED)$"
    )
    take_profit_mode: str | None = Field(
        default=None, pattern="^(INHERIT|ENABLED|DISABLED)$"
    )
    trailing_stop_mode: str | None = Field(
        default=None, pattern="^(INHERIT|ENABLED|DISABLED)$"
    )
    auto_trading_enabled: bool | None = None
    buy_enabled: bool | None = None
    sell_enabled: bool | None = None
    sell_only: bool | None = None
    account_paused: bool | None = None
    # STEP 8-7
    max_order_quantity: Decimal | None = Field(default=None, ge=0)
    daily_order_limit: int | None = Field(default=None, ge=0)
    daily_submit_limit: int | None = Field(default=None, ge=0)
    daily_filled_entry_limit: int | None = Field(default=None, ge=0)
    duplicate_order_window_seconds: int | None = Field(
        default=None, ge=0, le=3600
    )


def _payload(body: RiskSettingUpdateRequest) -> dict[str, Any]:
    return body.model_dump(exclude_unset=True)


@router.get("/system")
def get_system_risk_settings(
    session: Session = Depends(get_db_session),
):
    service = UserRiskSettingService(session)
    return {
        "stored": service.snapshot_system(),
        "resolved": service.resolve().as_dict(),
    }


@router.put("/system")
def put_system_risk_settings(
    body: RiskSettingUpdateRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    service = UserRiskSettingService(session)
    before = service.snapshot_system()
    try:
        service.update_system(
            _payload(body), actor=user.username
        )
        session.commit()
    except (RiskSettingValidationError, LookupError) as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    after = service.snapshot_system()
    audit.record(
        event_type="SYSTEM_RISK_SETTINGS_UPDATE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={"before": before, "after": after},
    )
    session.commit()
    return {"stored": after, "resolved": service.resolve().as_dict()}


@router.get("/users/{user_id}")
def get_user_risk_settings_admin(
    user_id: int,
    session: Session = Depends(get_db_session),
):
    service = UserRiskSettingService(session)
    return {
        "user_id": user_id,
        "stored": service.snapshot_user(user_id),
        "resolved": service.resolve(user_id=user_id).as_dict(),
    }


@router.put("/users/{user_id}")
def put_user_risk_settings_admin(
    user_id: int,
    body: RiskSettingUpdateRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    service = UserRiskSettingService(session)
    before = service.snapshot_user(user_id)
    try:
        service.upsert_user(
            user_id, _payload(body), actor=user.username
        )
        session.commit()
    except RiskSettingValidationError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    after = service.snapshot_user(user_id)
    audit.record(
        event_type="ADMIN_USER_RISK_SETTINGS_UPDATE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "target_user_id": user_id,
            "before": before,
            "after": after,
        },
    )
    session.commit()
    return {
        "user_id": user_id,
        "stored": after,
        "resolved": service.resolve(user_id=user_id).as_dict(),
    }


@router.get("/accounts/{user_broker_account_id}")
def get_account_risk_settings_admin(
    user_broker_account_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    uba = assert_broker_account_access(
        user, user_broker_account_id, session
    )
    service = UserRiskSettingService(session)
    return {
        "user_broker_account_id": user_broker_account_id,
        "user_id": int(uba.user_id),
        "stored": service.snapshot_account(user_broker_account_id),
        "resolved": service.resolve(
            user_id=int(uba.user_id),
            user_broker_account_id=user_broker_account_id,
        ).as_dict(),
    }


@router.put("/accounts/{user_broker_account_id}")
def put_account_risk_settings_admin(
    user_broker_account_id: int,
    body: RiskSettingUpdateRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    uba = assert_broker_account_access(
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
        event_type="ADMIN_ACCOUNT_RISK_SETTINGS_UPDATE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "target_user_id": int(uba.user_id),
            "user_broker_account_id": user_broker_account_id,
            "before": before,
            "after": after,
        },
    )
    session.commit()
    return {
        "user_broker_account_id": user_broker_account_id,
        "stored": after,
        "resolved": service.resolve(
            user_id=int(uba.user_id),
            user_broker_account_id=user_broker_account_id,
        ).as_dict(),
    }


class TradingFlagRequest(BaseModel):
    buy_enabled: bool | None = None
    sell_only: bool | None = None
    auto_trading_enabled: bool | None = None
    account_paused: bool | None = None


@router.post("/users/{user_id}/trading-flags")
def set_user_trading_flags(
    user_id: int,
    body: TradingFlagRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """매수 차단·매도 전용·자동매매 중지 등 플래그 일괄 설정."""

    service = UserRiskSettingService(session)
    before = service.snapshot_user(user_id)
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(
            status_code=400, detail="no flags provided"
        )
    try:
        service.upsert_user(
            user_id, payload, actor=user.username
        )
        session.commit()
    except RiskSettingValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    after = service.snapshot_user(user_id)
    event = "ADMIN_USER_TRADING_FLAGS_UPDATE"
    if payload.get("sell_only") is True:
        event = "ADMIN_USER_SELL_ONLY_ENABLE"
    elif payload.get("buy_enabled") is False:
        event = "ADMIN_USER_BUY_BLOCK"
    elif payload.get("auto_trading_enabled") is False:
        event = "ADMIN_USER_AUTO_TRADING_STOP"
    audit.record(
        event_type=event,
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "target_user_id": user_id,
            "before": before,
            "after": after,
        },
    )
    session.commit()
    return {"user_id": user_id, "stored": after}


@router.get("/accounts-by-user/{user_id}")
def list_user_broker_accounts_for_risk(
    user_id: int,
    session: Session = Depends(get_db_session),
):
    """ADMIN용 — 사용자에 연결된 UBA 목록(리스크 설정 대상)."""

    rows = list(
        session.scalars(
            select(UserBrokerAccount).where(
                UserBrokerAccount.user_id == int(user_id)
            )
        )
    )
    return {
        "items": [
            {
                "user_broker_account_id": int(r.user_broker_account_id),
                "broker_code": r.broker_code,
                "account_alias": r.account_alias,
                "masked_account_number": r.masked_account_number,
                "is_active": bool(r.is_active),
            }
            for r in rows
        ]
    }
