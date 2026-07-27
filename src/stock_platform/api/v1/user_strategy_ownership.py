"""STEP 8-3 — USER 전략 정의 CRUD·복제·계좌 연결."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import AuditLogService, get_audit_service
from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.performance.repository import (
    StrategyPerformanceRepository,
)
from stock_platform.strategy_deployment.ownership import (
    StrategyDefinitionService,
    StrategyOwnershipError,
    assert_strategy_readable,
)


router = APIRouter(
    prefix="/api/v1/user/strategies",
    tags=["User Strategy Ownership"],
)


class CreateStrategyBody(BaseModel):
    strategy_code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    market_type: str = "STOCK"
    parameter_payload: dict[str, Any] = Field(default_factory=dict)
    # 클라이언트가 넣어도 무시됨
    user_id: int | None = None
    owner_type: str | None = None
    visibility: str | None = None


class UpdateStrategyBody(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    market_type: str | None = None
    parameter_payload: dict[str, Any] | None = None
    is_active: bool | None = None
    user_id: int | None = None
    owner_type: str | None = None
    visibility: str | None = None


class CloneStrategyBody(BaseModel):
    name: str | None = Field(default=None, max_length=200)


class LinkStrategyBody(BaseModel):
    paper_account_id: int | None = Field(default=None, gt=0)
    user_broker_account_id: int | None = Field(default=None, gt=0)
    account_broker: str = Field(default="PAPER", max_length=30)


class BacktestRequestBody(BaseModel):
    """백테스트 실행은 소유권 검사 후 기존 performance run API로 위임 안내."""

    note: str | None = None


@router.get("")
def list_my_strategies(
    scope: str | None = Query(
        default=None,
        description="MINE | PUBLIC | (전체=본인+공개)",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    service = StrategyDefinitionService(session)
    rows = service.list_for_user(
        user, scope=scope, limit=limit, offset=offset
    )
    return {
        "items": [service.as_dict(r) for r in rows],
        "count": len(rows),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_my_strategy(
    body: CreateStrategyBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    # Body 위조 필드 거부 표시 (서버 강제 덮어쓰기)
    if body.owner_type and body.owner_type.upper() == "SYSTEM":
        raise HTTPException(
            status_code=400,
            detail="USER는 owner_type=SYSTEM 을 지정할 수 없습니다.",
        )
    if body.visibility and body.visibility.upper() == "PUBLIC":
        raise HTTPException(
            status_code=400,
            detail="USER는 visibility=PUBLIC 을 직접 지정할 수 없습니다.",
        )
    if body.user_id is not None and int(body.user_id) != int(user.user_id):
        raise HTTPException(
            status_code=400,
            detail="user_id 는 현재 로그인 사용자로만 생성됩니다.",
        )
    service = StrategyDefinitionService(session)
    try:
        row = service.create_user_strategy(
            user,
            strategy_code=body.strategy_code,
            name=body.name,
            description=body.description,
            market_type=body.market_type,
            parameter_payload=body.parameter_payload,
            actor=user.username,
        )
        session.commit()
    except StrategyOwnershipError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit.record(
        event_type="USER_STRATEGY_CREATE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(row.strategy_id),
        detail={
            "strategy_id": int(row.strategy_id),
            "owner_user_id": int(user.user_id),
            "strategy_code": row.strategy_code,
        },
    )
    session.commit()
    return service.as_dict(row)


@router.get("/{strategy_id}")
def get_my_strategy(
    strategy_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    service = StrategyDefinitionService(session)
    row = service.require(strategy_id)
    assert_strategy_readable(user, row)
    return service.as_dict(row)


@router.put("/{strategy_id}")
def update_my_strategy(
    strategy_id: int,
    body: UpdateStrategyBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    if body.owner_type and body.owner_type.upper() == "SYSTEM":
        raise HTTPException(status_code=400, detail="owner_type=SYSTEM 불가")
    if body.visibility and body.visibility.upper() == "PUBLIC":
        raise HTTPException(status_code=400, detail="visibility=PUBLIC 불가")
    if body.user_id is not None and int(body.user_id) != int(user.user_id):
        raise HTTPException(status_code=400, detail="타 user_id 지정 불가")
    service = StrategyDefinitionService(session)
    before = service.as_dict(service.require(strategy_id))
    try:
        row = service.update_user_strategy(
            user,
            strategy_id,
            payload=body.model_dump(exclude_unset=True),
            actor=user.username,
        )
        session.commit()
    except StrategyOwnershipError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        session.rollback()
        raise
    after = service.as_dict(row)
    audit.record(
        event_type="USER_STRATEGY_UPDATE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"before": before, "after": after},
    )
    session.commit()
    return after


@router.delete("/{strategy_id}")
def delete_my_strategy(
    strategy_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    service = StrategyDefinitionService(session)
    before = service.as_dict(service.require(strategy_id))
    try:
        row = service.soft_delete_user_strategy(
            user, strategy_id, actor=user.username
        )
        session.commit()
    except StrategyOwnershipError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        session.rollback()
        raise
    audit.record(
        event_type="USER_STRATEGY_SOFT_DELETE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"before": before, "strategy_id": strategy_id},
    )
    session.commit()
    return service.as_dict(row)


@router.post("/{strategy_id}/clone", status_code=status.HTTP_201_CREATED)
def clone_strategy(
    strategy_id: int,
    body: CloneStrategyBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    service = StrategyDefinitionService(session)
    try:
        row = service.clone_strategy(
            user, strategy_id, actor=user.username, name=body.name
        )
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    audit.record(
        event_type="USER_STRATEGY_CLONE",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(row.strategy_id),
        detail={
            "source_strategy_id": strategy_id,
            "new_strategy_id": int(row.strategy_id),
        },
    )
    session.commit()
    return service.as_dict(row)


@router.post("/{strategy_id}/backtest")
def backtest_strategy(
    strategy_id: int,
    body: BacktestRequestBody,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    """소유권 검사 후 백테스트 진입 가능 여부를 확인한다."""

    _ = body
    service = StrategyDefinitionService(session)
    row = service.require(strategy_id)
    assert_strategy_readable(user, row)
    return {
        "allowed": True,
        "strategy_id": int(row.strategy_id),
        "strategy_code": row.strategy_code,
        "message": (
            "전략 접근이 허용되었습니다. "
            "실제 실행은 POST /api/v1/user/backtests 또는 "
            "strategy-performance runs 를 사용하고 "
            "requested_by_user_id 에 본인 ID가 기록됩니다."
        ),
    }


@router.get("/{strategy_id}/performance-runs/{run_id}")
def get_strategy_performance_run_owned(
    strategy_id: int,
    run_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    service = StrategyDefinitionService(session)
    strategy = service.require(strategy_id)
    assert_strategy_readable(user, strategy)
    run, metric = StrategyPerformanceRepository(session).get_detail(
        run_id=run_id
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    # 타인 개인 전략 결과 차단
    if (
        not user.is_admin
        and getattr(run, "requested_by_user_id", None) is not None
        and int(run.requested_by_user_id) != int(user.user_id)
        and strategy.visibility != "PUBLIC"
    ):
        raise HTTPException(status_code=403, detail="권한 없음")
    if (
        getattr(run, "strategy_id", None) is not None
        and int(run.strategy_id) != int(strategy_id)
    ):
        raise HTTPException(status_code=400, detail="strategy_id mismatch")
    return {"run": run, "metric": metric}
