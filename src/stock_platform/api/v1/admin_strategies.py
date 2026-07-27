"""STEP 8-3 — ADMIN 전략 소유권·공개·승인."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.strategy_deployment.definition_entities import (
    StrategyDefinitionEntity,
)
from stock_platform.strategy_deployment.ownership import (
    StrategyDefinitionService,
    StrategyOwnershipError,
)


router = APIRouter(
    prefix="/api/v1/admin/strategies",
    tags=["Admin Strategies"],
    dependencies=[Depends(require_admin)],
)


class AdminCreateBody(BaseModel):
    strategy_code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    market_type: str = "STOCK"
    visibility: str = "PUBLIC"
    parameter_payload: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class AdminUpdateBody(BaseModel):
    name: str | None = None
    description: str | None = None
    market_type: str | None = None
    parameter_payload: dict[str, Any] | None = None
    is_active: bool | None = None


@router.get("")
def list_all_strategies(
    owner_type: str | None = None,
    user_id: int | None = None,
    visibility: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db_session),
):
    stmt = select(StrategyDefinitionEntity).where(
        StrategyDefinitionEntity.deleted_at.is_(None)
    )
    if owner_type:
        stmt = stmt.where(
            StrategyDefinitionEntity.owner_type == owner_type.upper()
        )
    if user_id is not None:
        stmt = stmt.where(StrategyDefinitionEntity.user_id == user_id)
    if visibility:
        stmt = stmt.where(
            StrategyDefinitionEntity.visibility == visibility.upper()
        )
    rows = list(
        session.scalars(
            stmt.order_by(StrategyDefinitionEntity.strategy_id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    service = StrategyDefinitionService(session)
    return {"items": [service.as_dict(r) for r in rows], "count": len(rows)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_system_strategy(
    body: AdminCreateBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    vis = body.visibility.upper()
    if vis not in {"PRIVATE", "PUBLIC"}:
        raise HTTPException(status_code=422, detail="invalid visibility")
    row = StrategyDefinitionEntity(
        strategy_code=body.strategy_code.strip(),
        name=body.name.strip(),
        description=body.description,
        market_type=body.market_type.upper(),
        owner_type="SYSTEM",
        user_id=None,
        visibility=vis,
        is_active=body.is_active,
        parameter_payload=dict(body.parameter_payload or {}),
        created_by=user.username,
        updated_by=user.username,
        published_by=user.username if vis == "PUBLIC" else None,
    )
    session.add(row)
    session.flush()
    session.commit()
    service = StrategyDefinitionService(session)
    audit.record(
        event_type="ADMIN_SYSTEM_STRATEGY_CREATE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(row.strategy_id),
        detail=service.as_dict(row),
    )
    session.commit()
    return service.as_dict(row)


@router.put("/{strategy_id}")
def update_strategy_admin(
    strategy_id: int,
    body: AdminUpdateBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    service = StrategyDefinitionService(session)
    row = service.require(strategy_id)
    before = service.as_dict(row)
    payload = body.model_dump(exclude_unset=True)
    for key, value in payload.items():
        if value is not None:
            setattr(row, key, value)
    row.updated_by = user.username
    session.commit()
    after = service.as_dict(row)
    audit.record(
        event_type="ADMIN_STRATEGY_UPDATE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"before": before, "after": after},
    )
    session.commit()
    return after


@router.post("/{strategy_id}/approve")
def approve_strategy(
    strategy_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    service = StrategyDefinitionService(session)
    before = service.as_dict(service.require(strategy_id))
    row = service.admin_approve(
        strategy_id, actor=user.username, approve=True
    )
    session.commit()
    after = service.as_dict(row)
    audit.record(
        event_type="ADMIN_STRATEGY_APPROVE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"before": before, "after": after},
    )
    session.commit()
    return after


@router.post("/{strategy_id}/reject")
def reject_strategy(
    strategy_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    service = StrategyDefinitionService(session)
    before = service.as_dict(service.require(strategy_id))
    row = service.admin_approve(
        strategy_id, actor=user.username, approve=False
    )
    session.commit()
    after = service.as_dict(row)
    audit.record(
        event_type="ADMIN_STRATEGY_REJECT",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"before": before, "after": after},
    )
    session.commit()
    return after


@router.post("/{strategy_id}/publish")
def publish_strategy(
    strategy_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    service = StrategyDefinitionService(session)
    before = service.as_dict(service.require(strategy_id))
    try:
        row = service.admin_set_visibility(
            strategy_id, visibility="PUBLIC", actor=user.username
        )
        session.commit()
    except StrategyOwnershipError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    after = service.as_dict(row)
    audit.record(
        event_type="ADMIN_STRATEGY_PUBLISH",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"before": before, "after": after},
    )
    session.commit()
    return after


@router.post("/{strategy_id}/unpublish")
def unpublish_strategy(
    strategy_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    service = StrategyDefinitionService(session)
    before = service.as_dict(service.require(strategy_id))
    row = service.admin_set_visibility(
        strategy_id, visibility="PRIVATE", actor=user.username
    )
    session.commit()
    after = service.as_dict(row)
    audit.record(
        event_type="ADMIN_STRATEGY_UNPUBLISH",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"before": before, "after": after},
    )
    session.commit()
    return after


@router.post("/{strategy_id}/activate")
def activate_strategy(
    strategy_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    service = StrategyDefinitionService(session)
    before = service.as_dict(service.require(strategy_id))
    row = service.admin_set_active(
        strategy_id, is_active=True, actor=user.username
    )
    session.commit()
    after = service.as_dict(row)
    audit.record(
        event_type="ADMIN_STRATEGY_ACTIVATE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"before": before, "after": after},
    )
    session.commit()
    return after


@router.post("/{strategy_id}/deactivate")
def deactivate_strategy(
    strategy_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    service = StrategyDefinitionService(session)
    before = service.as_dict(service.require(strategy_id))
    row = service.admin_set_active(
        strategy_id, is_active=False, actor=user.username
    )
    session.commit()
    after = service.as_dict(row)
    audit.record(
        event_type="ADMIN_STRATEGY_DEACTIVATE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"before": before, "after": after},
    )
    session.commit()
    return after
