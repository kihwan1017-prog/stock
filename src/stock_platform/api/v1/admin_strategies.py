"""STEP 8-3 — ADMIN 전략 소유권·공개·승인."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
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
    assert_strategy_not_draft_derived,
)
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalError,
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_draft_approval.readiness import (
    ReadinessError,
    check_readiness,
    validate_provenance,
)
from stock_platform.ai.strategy_draft_approval.backtest_spec import (
    BacktestSpecificationError,
    compile_specification,
)
from stock_platform.ai.strategy_draft_approval.backtest_execution import (
    BacktestExecutionError,
    run_definition_backtest,
)
from stock_platform.ai.strategy_draft_approval.walk_forward import (
    WalkForwardError,
    get_overfitting_report,
    get_walk_forward_detail,
    run_walk_forward,
)
from stock_platform.ai.strategy_draft_approval.quality_gate import (
    QualityGateError,
    get_quality_report,
    get_recommendation,
    run_quality_gate,
)
from stock_platform.ai.strategy_draft_approval.parameter_sensitivity import (
    ParameterSensitivityError,
    get_parameter_sensitivity_report,
    get_parameter_sensitivity_summary,
    get_parameter_sensitivity_variations,
    run_parameter_sensitivity,
)
from stock_platform.ai.strategy_draft_approval.monte_carlo import (
    BLOCK_SIZE_DEFAULT,
    CONFIDENCE_LEVEL_DEFAULT,
    RANDOM_SEED_DEFAULT,
    RUIN_THRESHOLD_PERCENT_DEFAULT,
    SIMULATION_COUNT_DEFAULT,
    MonteCarloError,
    get_monte_carlo_distribution,
    get_monte_carlo_report,
    get_monte_carlo_representatives,
    get_monte_carlo_summary,
    run_monte_carlo_simulation,
)
from stock_platform.ai.strategy_draft_approval.explainability import (
    DEFAULT_EXPLANATION_MODE,
    DEFAULT_LANGUAGE,
    ExplainabilityError,
    get_explainability_checklist,
    get_explainability_evidence,
    get_explainability_missing,
    get_explainability_report,
    get_explainability_summary,
    run_generate_explainability,
)
from stock_platform.ai.strategy_draft_approval.decision_package import (
    DecisionPackageError,
    get_decision_package_checklist,
    get_decision_package_report,
    get_decision_package_staleness,
    get_decision_package_summary,
    get_human_decision,
    get_promotion_readiness,
    run_create_decision_package,
    run_record_human_decision,
)
from stock_platform.ai.strategy_draft_approval.promotion_commit import (
    PromotionCommitError,
    get_promotion_commit,
    get_promotion_commit_history,
    get_promotion_commit_provenance,
    get_promotion_status,
    list_promotion_commits,
    run_create_promotion_commit,
)
from stock_platform.ai.strategy_draft_approval.activation import (
    ActivationError,
    get_activation_commit,
    get_activation_commit_provenance,
    get_activation_decision,
    get_activation_review_package,
    get_activation_review_package_checklist,
    get_activation_review_package_staleness,
    get_activation_status,
    list_activation_commits,
    list_activation_review_packages,
    run_create_activation_commit,
    run_create_activation_review_package,
    run_record_activation_decision,
)
from stock_platform.ai.strategy_draft_approval.runtime_registration import (
    RuntimeRegistrationError,
    get_runtime_registration_commit,
    get_runtime_registration_commit_provenance,
    get_runtime_registration_decision,
    get_runtime_registration_history,
    get_runtime_registration_package,
    get_runtime_registration_package_checklist,
    get_runtime_registration_package_staleness,
    get_runtime_registration_scopes,
    get_runtime_registration_status,
    list_runtime_registration_commits,
    list_runtime_registration_packages,
    run_create_runtime_registration_commit,
    run_create_runtime_registration_package,
    run_record_runtime_registration_decision,
)
from stock_platform.ai.strategy_draft_approval.deployment_readiness import (
    DeploymentReadinessError,
    get_deployment_readiness_commit,
    get_deployment_readiness_commit_provenance,
    get_deployment_readiness_decision,
    get_deployment_readiness_history,
    get_deployment_readiness_package,
    get_deployment_readiness_package_checklist,
    get_deployment_readiness_package_staleness,
    get_deployment_readiness_scopes,
    get_deployment_readiness_status,
    get_scheduler_plan,
    list_deployment_readiness_commits,
    list_deployment_readiness_packages,
    list_scheduler_plans,
    run_create_deployment_readiness_commit,
    run_create_deployment_readiness_package,
    run_record_deployment_readiness_decision,
)
from stock_platform.ai.strategy_draft_approval.operation_readiness import (
    OperationReadinessError,
    get_operation_readiness_certification,
    get_operation_readiness_commit,
    get_operation_readiness_commit_provenance,
    get_operation_readiness_decision,
    get_operation_readiness_history,
    get_operation_readiness_package,
    get_operation_readiness_package_checklist,
    get_operation_readiness_package_staleness,
    get_operation_readiness_status,
    list_operation_readiness_commits,
    list_operation_readiness_packages,
    run_create_operation_readiness_commit,
    run_create_operation_readiness_package,
    run_record_operation_readiness_decision,
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
    try:
        assert_strategy_not_draft_derived(row)
    except HTTPException:
        session.rollback()
        raise
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


# ---------------------------------------------------------------------------
# STEP12-4 — Strategy Snapshot(승인으로 생성된 불변 Definition) 조회/이력/Export.
# 새 Snapshot 테이블/API 그룹을 만들지 않고 기존 admin/strategies 라우터에
# 최소 엔드포인트만 추가한다. Import(외부 JSON으로 Definition 생성/수정)는
# 의도적으로 제공하지 않는다 — Definition은 오직 Draft 승인 경로로만 생성.
# ---------------------------------------------------------------------------


def _raise_snapshot(exc: StrategyDraftApprovalError) -> None:
    code = status.HTTP_404_NOT_FOUND if exc.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
    raise HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message})


@router.get("/{strategy_id}/snapshot")
def get_strategy_snapshot(
    strategy_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        snapshot = StrategyDraftApprovalService(session).get_snapshot(strategy_id)
    except StrategyDraftApprovalError as exc:
        _raise_snapshot(exc)
        return {}
    audit.record(
        event_type="STRATEGY_SNAPSHOT_VIEWED",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={
            "definition_hash": snapshot["definition_hash"],
            "hash_valid": snapshot["hash_valid"],
        },
    )
    session.commit()
    return snapshot


@router.get("/{strategy_id}/snapshot/history")
def get_strategy_snapshot_history(
    strategy_id: int,
    session: Session = Depends(get_db_session),
    _admin: AuthenticatedUser = Depends(require_admin),
):
    try:
        return StrategyDraftApprovalService(session).get_snapshot_history(strategy_id)
    except StrategyDraftApprovalError as exc:
        _raise_snapshot(exc)
        return {}


@router.get("/{strategy_id}/snapshot/export")
def export_strategy_snapshot(
    strategy_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        bundle = StrategyDraftApprovalService(session).export_snapshot(strategy_id)
    except StrategyDraftApprovalError as exc:
        audit.record(
            event_type="STRATEGY_SNAPSHOT_VALIDATION_FAILED",
            actor=user.username,
            request_id=getattr(http_request.state, "request_id", None),
            strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        _raise_snapshot(exc)
        return {}
    audit.record(
        event_type="STRATEGY_SNAPSHOT_EXPORTED",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"definition_hash": bundle["definition_hash"]},
    )
    session.commit()
    return bundle


# ---------------------------------------------------------------------------
# STEP12-5 — Backtest Readiness / Provenance Chain 검증(읽기 전용).
# 새 Entity/Table 없이 STEP12-2-1/12-2-2/12-3 엔티티만 교차 조회한다.
# ---------------------------------------------------------------------------


def _raise_readiness(exc: ReadinessError) -> None:
    code = status.HTTP_404_NOT_FOUND if exc.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message})


@router.get("/{strategy_id}/readiness")
def get_strategy_readiness(
    strategy_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = check_readiness(session, strategy_id)
    except ReadinessError as exc:
        _raise_readiness(exc)
        return {}
    audit.record(
        event_type="READINESS_CHECK" if result["ready"] else "READINESS_FAILED",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"ready": result["ready"], "failure_reasons": result["failure_reasons"]},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/provenance")
def get_strategy_provenance(
    strategy_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = validate_provenance(session, strategy_id)
    except ReadinessError as exc:
        _raise_readiness(exc)
        return {}
    audit.record(
        event_type="PROVENANCE_VALIDATED",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"valid": result["valid"], "failures": result["failures"]},
    )
    session.commit()
    return result


# ---------------------------------------------------------------------------
# STEP12-6 — 승인된 Strategy Definition -> Backtest Executable Specification
# (Compile/Validate/Explain/Preview만 — 실제 Backtest 실행/Run 생성 없음,
# DB WRITE 없음, Definition 미수정). "compilability"는 이 응답의
# `compilable` 필드로 이미 표현되므로 별도 엔드포인트를 중복 추가하지
# 않는다.
# ---------------------------------------------------------------------------


@router.get("/{strategy_id}/backtest-specification")
def get_strategy_backtest_specification(
    strategy_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = compile_specification(session, strategy_id)
    except BacktestSpecificationError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if exc.code == "NOT_FOUND"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=code, detail={"code": exc.code, "message": exc.message}
        )
    audit.record(
        event_type=(
            "STRATEGY_BACKTEST_SPEC_COMPILED"
            if result["compilable"]
            else "STRATEGY_BACKTEST_SPEC_VALIDATION_FAILED"
        ),
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={
            "definition_version": result["definition_version"],
            "compiler_version": result["compiler_version"],
            "executable_hash": result["executable_hash"],
            "compilable": result["compilable"],
            "errors": result["errors"],
        },
    )
    session.commit()
    return result


# ---------------------------------------------------------------------------
# STEP12-7 — 승인 Strategy Definition 기반 과거 데이터 Backtest 실행(Admin
# 전용). Broker/Order/Runtime/Scheduler WRITE 없음 — 기존
# backtest.backtest_run(+trade/equity)에만 기록한다(§14, 새 테이블 없음).
# ---------------------------------------------------------------------------


class RunDefinitionBacktestBody(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)
    exchange_code: str = Field(min_length=1, max_length=20)
    start_date: date
    end_date: date
    initial_capital: Decimal = Field(gt=0)
    fee_ratio: Decimal = Field(default=Decimal("0.00015"), ge=0, le=Decimal("0.20"))
    sell_tax_ratio: Decimal = Field(default=Decimal("0.0018"), ge=0, le=Decimal("0.20"))
    slippage_ratio: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("0.20"))
    idempotency_key: str | None = Field(default=None, max_length=64)


_BACKTEST_ERROR_STATUS = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "DEFINITION_NOT_READY": status.HTTP_409_CONFLICT,
    "PROVENANCE_INVALID": status.HTTP_409_CONFLICT,
    "RUNTIME_INPUT_REQUIRED": status.HTTP_400_BAD_REQUEST,
}


@router.post("/{strategy_id}/backtests", status_code=status.HTTP_201_CREATED)
def create_strategy_backtest(
    strategy_id: int,
    body: RunDefinitionBacktestBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    runtime_input = {
        "symbol": body.symbol,
        "exchange_code": body.exchange_code,
        "start_date": body.start_date,
        "end_date": body.end_date,
        "initial_capital": body.initial_capital,
        "fee_ratio": body.fee_ratio,
        "sell_tax_ratio": body.sell_tax_ratio,
        "slippage_ratio": body.slippage_ratio,
    }
    audit.record(
        event_type="STRATEGY_BACKTEST_REQUESTED",
        actor=actor,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"symbol": body.symbol, "exchange_code": body.exchange_code},
    )
    session.commit()
    try:
        result = run_definition_backtest(
            session,
            strategy_id,
            runtime_input=runtime_input,
            actor=actor,
            idempotency_key=body.idempotency_key,
        )
    except BacktestExecutionError as exc:
        audit.record(
            event_type="STRATEGY_BACKTEST_FAILED",
            actor=actor,
            request_id=getattr(http_request.state, "request_id", None),
            strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        code = _BACKTEST_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST)
        raise HTTPException(
            status_code=code, detail={"code": exc.code, "message": exc.message}
        )

    audit.record(
        event_type=(
            "STRATEGY_BACKTEST_DUPLICATE_REPLAYED"
            if result["idempotent_replay"]
            else "STRATEGY_BACKTEST_SUCCEEDED"
        ),
        actor=actor,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={
            "backtest_run_id": result["backtest_run_id"],
            "trade_count": result["summary"]["trade_count"],
            "total_return_rate": str(result["summary"]["total_return_rate"]),
        },
    )
    session.commit()
    return result


# ---------------------------------------------------------------------------
# STEP12-9 — 승인 Strategy Definition의 Walk-Forward Analysis(In-Sample/
# Out-of-Sample 자동 분리, Rolling/Expanding). 기존 STEP12-7
# run_definition_backtest()/STEP12-8 analyze_backtest_run()를 그대로
# 재사용하며, 새 BacktestEngine/Table을 만들지 않는다(§ walk_forward.py
# 참고 — 기존 trading.strategy_performance_run/walk_forward_window_metric
# 재사용).
# ---------------------------------------------------------------------------


class RunWalkForwardBody(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)
    exchange_code: str = Field(min_length=1, max_length=20)
    start_date: date
    end_date: date
    train_days: int = Field(gt=0, le=3650)
    test_days: int = Field(gt=0, le=3650)
    window_scheme: str = Field(default="ROLLING")
    initial_capital: Decimal = Field(gt=0)
    fee_ratio: Decimal = Field(default=Decimal("0.00015"), ge=0, le=Decimal("0.20"))
    sell_tax_ratio: Decimal = Field(default=Decimal("0.0018"), ge=0, le=Decimal("0.20"))
    slippage_ratio: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("0.20"))


_WALK_FORWARD_ERROR_STATUS = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "DEFINITION_NOT_READY": status.HTTP_409_CONFLICT,
    "PROVENANCE_INVALID": status.HTTP_409_CONFLICT,
    "RUNTIME_INPUT_REQUIRED": status.HTTP_400_BAD_REQUEST,
    "INVALID_WINDOW": status.HTTP_400_BAD_REQUEST,
    "INVALID_WINDOW_SCHEME": status.HTTP_400_BAD_REQUEST,
    "ALL_WINDOWS_FAILED": status.HTTP_400_BAD_REQUEST,
}


@router.post("/{strategy_id}/walk-forward", status_code=status.HTTP_201_CREATED)
def create_strategy_walk_forward(
    strategy_id: int,
    body: RunWalkForwardBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="WALK_FORWARD_STARTED",
        actor=actor,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={
            "symbol": body.symbol,
            "exchange_code": body.exchange_code,
            "window_scheme": body.window_scheme,
            "train_days": body.train_days,
            "test_days": body.test_days,
        },
    )
    session.commit()
    try:
        result = run_walk_forward(
            session,
            strategy_id,
            start_date=body.start_date,
            end_date=body.end_date,
            train_days=body.train_days,
            test_days=body.test_days,
            scheme=body.window_scheme.upper(),
            symbol=body.symbol,
            exchange_code=body.exchange_code,
            initial_capital=body.initial_capital,
            fee_ratio=body.fee_ratio,
            sell_tax_ratio=body.sell_tax_ratio,
            slippage_ratio=body.slippage_ratio,
            actor=actor,
        )
    except (WalkForwardError, BacktestExecutionError, BacktestSpecificationError) as exc:
        code = getattr(exc, "code", "RUNTIME_INPUT_REQUIRED")
        message = getattr(exc, "message", str(exc))
        audit.record(
            event_type="WALK_FORWARD_FAILED",
            actor=actor,
            request_id=getattr(http_request.state, "request_id", None),
            strategy_id=str(strategy_id),
            detail={"code": code, "message": message},
        )
        session.commit()
        raise HTTPException(
            status_code=_WALK_FORWARD_ERROR_STATUS.get(code, status.HTTP_400_BAD_REQUEST),
            detail={"code": code, "message": message},
        )

    audit.record(
        event_type="WALK_FORWARD_COMPLETED",
        actor=actor,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={
            "strategy_performance_run_id": result["strategy_performance_run_id"],
            "completed_window_count": result["completed_window_count"],
            "failed_window_count": result["failed_window_count"],
            "overfitting_grade": result["overfitting_grade"],
        },
    )
    session.commit()
    return result


@router.get("/{strategy_id}/walk-forward/{run_id}")
def get_strategy_walk_forward(
    strategy_id: int,
    run_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    try:
        return get_walk_forward_detail(session, run_id)
    except WalkForwardError as exc:
        raise HTTPException(
            status_code=_WALK_FORWARD_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        )


@router.get("/{strategy_id}/walk-forward/{run_id}/overfitting")
def get_strategy_walk_forward_overfitting(
    strategy_id: int,
    run_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_overfitting_report(session, run_id)
    except WalkForwardError as exc:
        raise HTTPException(
            status_code=_WALK_FORWARD_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        )
    audit.record(
        event_type="OVERFITTING_ANALYZED",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={
            "overfitting_score": result["overfitting_score"],
            "overfitting_grade": result["overfitting_grade"],
        },
    )
    session.commit()
    return result


# ---------------------------------------------------------------------------
# STEP12-10 — Strategy Quality Gate(기존 Backtest/Performance Analytics/
# Walk-Forward 결과만 재사용, 새 Backtest 실행 없음). 새 Backtest/Walk-
# Forward 구조를 만들지 않는다(§ quality_gate.py 참고 — 평가 결과 저장을
# 위한 최소 신규 테이블 1개만 Migration으로 추가).
# ---------------------------------------------------------------------------


_QUALITY_GATE_ERROR_STATUS = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "NO_BACKTEST_AVAILABLE": status.HTTP_400_BAD_REQUEST,
}


@router.post("/{strategy_id}/quality-gate", status_code=status.HTTP_201_CREATED)
def create_strategy_quality_gate(
    strategy_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="QUALITY_GATE_STARTED",
        actor=actor,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={},
    )
    session.commit()
    try:
        result = run_quality_gate(session, strategy_id, actor=actor)
    except QualityGateError as exc:
        audit.record(
            event_type="QUALITY_GATE_FAILED",
            actor=actor,
            request_id=getattr(http_request.state, "request_id", None),
            strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(
            status_code=_QUALITY_GATE_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        )

    audit.record(
        event_type="QUALITY_GATE_COMPLETED",
        actor=actor,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={
            "quality_gate_report_id": result["quality_gate_report_id"],
            "recommendation": result["recommendation"],
            "risk_grade": result["risk_grade"],
        },
    )
    session.commit()
    return result


@router.get("/{strategy_id}/quality-gate/{report_id}")
def get_strategy_quality_gate(
    strategy_id: int,
    report_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    try:
        return get_quality_report(session, report_id, strategy_definition_id=strategy_id)
    except QualityGateError as exc:
        raise HTTPException(
            status_code=_QUALITY_GATE_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        )


@router.get("/{strategy_id}/quality-gate/{report_id}/recommendation")
def get_strategy_quality_gate_recommendation(
    strategy_id: int,
    report_id: int,
    _user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    try:
        return get_recommendation(session, report_id, strategy_definition_id=strategy_id)
    except QualityGateError as exc:
        raise HTTPException(
            status_code=_QUALITY_GATE_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        )


# ---------------------------------------------------------------------------
# STEP12-11 — Parameter Sensitivity Analysis(기존 Backtest 실행 경로/
# Performance Analytics/Executable Specification만 재사용, 원본 Definition
# 미수정, 자동 최적화/Best Parameter 선택 없음). Quality Gate 판정은
# 이 STEP에서 전혀 변경하지 않는다(§ parameter_sensitivity.py 참고).
# ---------------------------------------------------------------------------


class RunParameterSensitivityBody(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)
    exchange_code: str = Field(min_length=1, max_length=20)
    start_date: date
    end_date: date
    initial_capital: Decimal = Field(gt=0)
    fee_ratio: Decimal = Field(default=Decimal("0.00015"), ge=0, le=Decimal("0.20"))
    sell_tax_ratio: Decimal = Field(default=Decimal("0.0018"), ge=0, le=Decimal("0.20"))
    slippage_ratio: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("0.20"))
    parameter_names: list[str] = Field(min_length=1, max_length=2)
    variation_ratios: list[Decimal] | None = None
    idempotency_key: str | None = Field(default=None, max_length=64)


_PARAMETER_SENSITIVITY_ERROR_STATUS = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "DEFINITION_NOT_READY": status.HTTP_409_CONFLICT,
    "PROVENANCE_INVALID": status.HTTP_409_CONFLICT,
    "RUNTIME_INPUT_REQUIRED": status.HTTP_400_BAD_REQUEST,
    "UNSUPPORTED_PARAMETER": status.HTTP_400_BAD_REQUEST,
    "TOO_MANY_PARAMETERS": status.HTTP_400_BAD_REQUEST,
    "COMBINATION_LIMIT_EXCEEDED": status.HTTP_400_BAD_REQUEST,
    "INVALID_PARAMETER_RANGE": status.HTTP_400_BAD_REQUEST,
}


@router.post("/{strategy_id}/parameter-sensitivity", status_code=status.HTTP_201_CREATED)
def create_strategy_parameter_sensitivity(
    strategy_id: int,
    body: RunParameterSensitivityBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    runtime_input = {
        "symbol": body.symbol,
        "exchange_code": body.exchange_code,
        "start_date": body.start_date,
        "end_date": body.end_date,
        "initial_capital": body.initial_capital,
        "fee_ratio": body.fee_ratio,
        "sell_tax_ratio": body.sell_tax_ratio,
        "slippage_ratio": body.slippage_ratio,
    }
    audit.record(
        event_type="PARAMETER_SENSITIVITY_STARTED",
        actor=actor,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"parameter_names": body.parameter_names},
    )
    session.commit()
    try:
        result = run_parameter_sensitivity(
            session,
            strategy_id,
            parameter_names=body.parameter_names,
            runtime_input=runtime_input,
            actor=actor,
            variation_ratios=tuple(body.variation_ratios) if body.variation_ratios else None,
            idempotency_key=body.idempotency_key,
        )
    except ParameterSensitivityError as exc:
        audit.record(
            event_type="PARAMETER_SENSITIVITY_FAILED",
            actor=actor,
            request_id=getattr(http_request.state, "request_id", None),
            strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(
            status_code=_PARAMETER_SENSITIVITY_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        )

    audit.record(
        event_type="PARAMETER_SENSITIVITY_COMPLETED",
        actor=actor,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={
            "parameter_sensitivity_report_id": result["parameter_sensitivity_report_id"],
            "sensitivity_status": result["sensitivity_status"],
            "robustness_score": (
                str(result["robustness_score"]) if result["robustness_score"] is not None else None
            ),
        },
    )
    session.commit()
    return result


@router.get("/{strategy_id}/parameter-sensitivity/{report_id}")
def get_strategy_parameter_sensitivity(
    strategy_id: int,
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_parameter_sensitivity_report(session, report_id, strategy_definition_id=strategy_id)
    except ParameterSensitivityError as exc:
        raise HTTPException(
            status_code=_PARAMETER_SENSITIVITY_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        )
    audit.record(
        event_type="PARAMETER_SENSITIVITY_VIEWED",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"parameter_sensitivity_report_id": report_id, "view": "detail"},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/parameter-sensitivity/{report_id}/summary")
def get_strategy_parameter_sensitivity_summary(
    strategy_id: int,
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_parameter_sensitivity_summary(session, report_id, strategy_definition_id=strategy_id)
    except ParameterSensitivityError as exc:
        raise HTTPException(
            status_code=_PARAMETER_SENSITIVITY_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        )
    audit.record(
        event_type="PARAMETER_SENSITIVITY_VIEWED",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"parameter_sensitivity_report_id": report_id, "view": "summary"},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/parameter-sensitivity/{report_id}/variations")
def get_strategy_parameter_sensitivity_variations(
    strategy_id: int,
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_parameter_sensitivity_variations(session, report_id, strategy_definition_id=strategy_id)
    except ParameterSensitivityError as exc:
        raise HTTPException(
            status_code=_PARAMETER_SENSITIVITY_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        )
    audit.record(
        event_type="PARAMETER_SENSITIVITY_VIEWED",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"parameter_sensitivity_report_id": report_id, "view": "variations"},
    )
    session.commit()
    return result


# ---------------------------------------------------------------------------
# STEP12-12 — Monte Carlo Simulation(기존 Backtest Trade 결과만 재사용, 새
# Backtest/매매 신호 생성 없음, Strategy Definition 미수정). Quality
# Gate/Parameter Sensitivity/Strategy 승인 상태는 전혀 변경하지 않는다
# (§ monte_carlo.py 참고).
# ---------------------------------------------------------------------------


class RunMonteCarloBody(BaseModel):
    backtest_run_id: int
    simulation_method: str
    simulation_count: int = Field(default=SIMULATION_COUNT_DEFAULT)
    random_seed: int = Field(default=RANDOM_SEED_DEFAULT)
    confidence_level: Decimal = Field(default=CONFIDENCE_LEVEL_DEFAULT)
    ruin_threshold_percent: Decimal = Field(default=RUIN_THRESHOLD_PERCENT_DEFAULT)
    block_size: int = Field(default=BLOCK_SIZE_DEFAULT)
    idempotency_key: str | None = Field(default=None, max_length=64)


_MONTE_CARLO_ERROR_STATUS = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "BACKTEST_RUN_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "OWNERSHIP_MISMATCH": status.HTTP_409_CONFLICT,
    "PROVENANCE_MISMATCH": status.HTTP_409_CONFLICT,
    "UNSUPPORTED_METHOD": status.HTTP_400_BAD_REQUEST,
    "INVALID_SIMULATION_COUNT": status.HTTP_400_BAD_REQUEST,
    "INVALID_CONFIDENCE_LEVEL": status.HTTP_400_BAD_REQUEST,
    "INVALID_RUIN_THRESHOLD": status.HTTP_400_BAD_REQUEST,
    "INVALID_BLOCK_SIZE": status.HTTP_400_BAD_REQUEST,
    "INVALID_RANDOM_SEED": status.HTTP_400_BAD_REQUEST,
    "INSUFFICIENT_TRADES": status.HTTP_400_BAD_REQUEST,
    "BACKTEST_NOT_COMPLETED": status.HTTP_409_CONFLICT,
    "EXECUTABLE_HASH_MISSING": status.HTTP_409_CONFLICT,
    "RUNTIME_INPUT_HASH_MISSING": status.HTTP_409_CONFLICT,
    "IDEMPOTENCY_CONFLICT": status.HTTP_409_CONFLICT,
}


@router.post("/{strategy_id}/monte-carlo", status_code=status.HTTP_201_CREATED)
def create_strategy_monte_carlo(
    strategy_id: int,
    body: RunMonteCarloBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="MONTE_CARLO_STARTED",
        actor=actor,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={
            "backtest_run_id": body.backtest_run_id,
            "simulation_method": body.simulation_method,
            "simulation_count": body.simulation_count,
        },
    )
    session.commit()
    try:
        result = run_monte_carlo_simulation(
            session,
            strategy_id,
            backtest_run_id=body.backtest_run_id,
            simulation_method=body.simulation_method,
            actor=actor,
            simulation_count=body.simulation_count,
            random_seed=body.random_seed,
            confidence_level=body.confidence_level,
            ruin_threshold_percent=body.ruin_threshold_percent,
            block_size=body.block_size,
            idempotency_key=body.idempotency_key,
        )
    except MonteCarloError as exc:
        audit.record(
            event_type="MONTE_CARLO_FAILED",
            actor=actor,
            request_id=getattr(http_request.state, "request_id", None),
            strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(
            status_code=_MONTE_CARLO_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        )

    audit.record(
        event_type="MONTE_CARLO_COMPLETED",
        actor=actor,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={
            "monte_carlo_report_id": result["monte_carlo_report_id"],
            "monte_carlo_status": result["monte_carlo_status"],
            "robustness_score": (
                str(result["robustness_score"]) if result["robustness_score"] is not None else None
            ),
        },
    )
    session.commit()
    return {
        "report_id": result["monte_carlo_report_id"],
        "status": result["monte_carlo_status"],
        "robustness_score": result["robustness_score"],
        "risk_of_ruin_percent": result["risk_of_ruin_percent"],
        "summary": {
            "valid_simulation_count": result["valid_simulation_count"],
            "failed_simulation_count": result["failed_simulation_count"],
            "trade_count": result["trade_count"],
        },
        "idempotent_replay": result["idempotent_replay"],
    }


@router.get("/{strategy_id}/monte-carlo/{report_id}")
def get_strategy_monte_carlo(
    strategy_id: int,
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_monte_carlo_report(session, report_id, strategy_definition_id=strategy_id)
    except MonteCarloError as exc:
        raise HTTPException(
            status_code=_MONTE_CARLO_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        )
    audit.record(
        event_type="MONTE_CARLO_VIEWED",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"monte_carlo_report_id": report_id, "view": "detail"},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/monte-carlo/{report_id}/summary")
def get_strategy_monte_carlo_summary(
    strategy_id: int,
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_monte_carlo_summary(session, report_id, strategy_definition_id=strategy_id)
    except MonteCarloError as exc:
        raise HTTPException(
            status_code=_MONTE_CARLO_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        )
    audit.record(
        event_type="MONTE_CARLO_VIEWED",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"monte_carlo_report_id": report_id, "view": "summary"},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/monte-carlo/{report_id}/distribution")
def get_strategy_monte_carlo_distribution(
    strategy_id: int,
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_monte_carlo_distribution(session, report_id, strategy_definition_id=strategy_id)
    except MonteCarloError as exc:
        raise HTTPException(
            status_code=_MONTE_CARLO_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        )
    audit.record(
        event_type="MONTE_CARLO_VIEWED",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"monte_carlo_report_id": report_id, "view": "distribution"},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/monte-carlo/{report_id}/representatives")
def get_strategy_monte_carlo_representatives(
    strategy_id: int,
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_monte_carlo_representatives(session, report_id, strategy_definition_id=strategy_id)
    except MonteCarloError as exc:
        raise HTTPException(
            status_code=_MONTE_CARLO_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
            detail={"code": exc.code, "message": exc.message},
        )
    audit.record(
        event_type="MONTE_CARLO_VIEWED",
        actor=user.username,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={"monte_carlo_report_id": report_id, "view": "representatives"},
    )
    session.commit()
    return result


# ---------------------------------------------------------------------------
# STEP12-14 — Strategy Explainability & Decision Evidence Layer(기존 Strategy
# Definition + 기존 검증 Report만 재구성, 새 계산/자동 승인 없음).
# ---------------------------------------------------------------------------


class RunExplainabilityBody(BaseModel):
    # § STEP12-15 인수 조건(STEP12-14 필수 인수 보완 3) — performance_run_id
    # 필드는 제거했다. 이 프로젝트에는 Backtest와 별개인 "Performance Run"
    # PK가 없다(Performance는 backtest_run.parameters에 종속). 이름과
    # 실제 의미가 다른 alias 필드를 남기지 않는다.
    backtest_run_id: int | None = None
    walk_forward_run_id: int | None = None
    quality_gate_report_id: int | None = None
    parameter_sensitivity_report_id: int | None = None
    monte_carlo_report_id: int | None = None
    portfolio_validation_report_id: int | None = None
    explanation_language: str = Field(default=DEFAULT_LANGUAGE)
    explanation_mode: str = Field(default=DEFAULT_EXPLANATION_MODE)
    use_latest_when_missing: bool = Field(default=True)
    idempotency_key: str | None = Field(default=None, max_length=64)


_EXPLAINABILITY_ERROR_STATUS = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "BACKTEST_RUN_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "OWNERSHIP_MISMATCH": status.HTTP_409_CONFLICT,
    "DEFINITION_NOT_READY": status.HTTP_409_CONFLICT,
    "SPECIFICATION_NOT_COMPILABLE": status.HTTP_409_CONFLICT,
    "UNSUPPORTED_EXPLANATION_MODE": status.HTTP_400_BAD_REQUEST,
    "UNSUPPORTED_LANGUAGE": status.HTTP_400_BAD_REQUEST,
    "IDEMPOTENCY_CONFLICT": status.HTTP_409_CONFLICT,
}


def _explainability_error_status(code: str) -> int:
    return _EXPLAINABILITY_ERROR_STATUS.get(code, status.HTTP_400_BAD_REQUEST)


@router.post("/{strategy_id}/explainability", status_code=status.HTTP_201_CREATED)
def create_strategy_explainability(
    strategy_id: int,
    body: RunExplainabilityBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="EXPLAINABILITY_STARTED",
        actor=actor,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={
            "backtest_run_id": body.backtest_run_id,
            "explanation_mode": body.explanation_mode,
            "explanation_language": body.explanation_language,
        },
    )
    session.commit()
    try:
        result = run_generate_explainability(
            session,
            strategy_id,
            backtest_run_id=body.backtest_run_id,
            walk_forward_run_id=body.walk_forward_run_id,
            quality_gate_report_id=body.quality_gate_report_id,
            parameter_sensitivity_report_id=body.parameter_sensitivity_report_id,
            monte_carlo_report_id=body.monte_carlo_report_id,
            portfolio_validation_report_id=body.portfolio_validation_report_id,
            explanation_language=body.explanation_language,
            explanation_mode=body.explanation_mode,
            use_latest_when_missing=body.use_latest_when_missing,
            actor=actor,
            idempotency_key=body.idempotency_key,
        )
    except ExplainabilityError as exc:
        audit.record(
            event_type="EXPLAINABILITY_FAILED",
            actor=actor,
            request_id=getattr(http_request.state, "request_id", None),
            strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(
            status_code=_explainability_error_status(exc.code), detail={"code": exc.code, "message": exc.message}
        )

    audit.record(
        event_type="EXPLAINABILITY_COMPLETED",
        actor=actor,
        request_id=getattr(http_request.state, "request_id", None),
        strategy_id=str(strategy_id),
        detail={
            "report_id": result["explainability_report_id"],
            "completeness_score": str(result["completeness_score"]),
            "completeness_status": result["completeness_status"],
        },
    )
    session.commit()
    return {
        "report_id": result["explainability_report_id"],
        "completeness_score": result["completeness_score"],
        "completeness_status": result["completeness_status"],
        "decision_summary": result["decision_summary"],
        "idempotent_replay": result["idempotent_replay"],
    }


def _record_explainability_viewed(
    audit: AuditLogService, *, actor: str, request_id, strategy_id: int, report_id: int, view: str
) -> None:
    audit.record(
        event_type="EXPLAINABILITY_VIEWED", actor=actor, request_id=request_id, strategy_id=str(strategy_id),
        detail={"report_id": report_id, "view": view},
    )


@router.get("/{strategy_id}/explainability/{report_id}")
def get_strategy_explainability(
    strategy_id: int,
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_explainability_report(session, report_id, strategy_definition_id=strategy_id)
    except ExplainabilityError as exc:
        raise HTTPException(
            status_code=_explainability_error_status(exc.code), detail={"code": exc.code, "message": exc.message}
        )
    _record_explainability_viewed(
        audit, actor=user.username, request_id=getattr(http_request.state, "request_id", None),
        strategy_id=strategy_id, report_id=report_id, view="detail",
    )
    session.commit()
    return result


@router.get("/{strategy_id}/explainability/{report_id}/summary")
def get_strategy_explainability_summary(
    strategy_id: int,
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_explainability_summary(session, report_id, strategy_definition_id=strategy_id)
    except ExplainabilityError as exc:
        raise HTTPException(
            status_code=_explainability_error_status(exc.code), detail={"code": exc.code, "message": exc.message}
        )
    _record_explainability_viewed(
        audit, actor=user.username, request_id=getattr(http_request.state, "request_id", None),
        strategy_id=strategy_id, report_id=report_id, view="summary",
    )
    session.commit()
    return result


@router.get("/{strategy_id}/explainability/{report_id}/evidence")
def get_strategy_explainability_evidence(
    strategy_id: int,
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_explainability_evidence(session, report_id, strategy_definition_id=strategy_id)
    except ExplainabilityError as exc:
        raise HTTPException(
            status_code=_explainability_error_status(exc.code), detail={"code": exc.code, "message": exc.message}
        )
    _record_explainability_viewed(
        audit, actor=user.username, request_id=getattr(http_request.state, "request_id", None),
        strategy_id=strategy_id, report_id=report_id, view="evidence",
    )
    session.commit()
    return result


@router.get("/{strategy_id}/explainability/{report_id}/checklist")
def get_strategy_explainability_checklist(
    strategy_id: int,
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_explainability_checklist(session, report_id, strategy_definition_id=strategy_id)
    except ExplainabilityError as exc:
        raise HTTPException(
            status_code=_explainability_error_status(exc.code), detail={"code": exc.code, "message": exc.message}
        )
    _record_explainability_viewed(
        audit, actor=user.username, request_id=getattr(http_request.state, "request_id", None),
        strategy_id=strategy_id, report_id=report_id, view="checklist",
    )
    session.commit()
    return result


@router.get("/{strategy_id}/explainability/{report_id}/missing")
def get_strategy_explainability_missing(
    strategy_id: int,
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_explainability_missing(session, report_id, strategy_definition_id=strategy_id)
    except ExplainabilityError as exc:
        raise HTTPException(
            status_code=_explainability_error_status(exc.code), detail={"code": exc.code, "message": exc.message}
        )
    _record_explainability_viewed(
        audit, actor=user.username, request_id=getattr(http_request.state, "request_id", None),
        strategy_id=strategy_id, report_id=report_id, view="missing",
    )
    session.commit()
    return result


# ---------------------------------------------------------------------------
# STEP12-15 — Decision Package & Human Decision(사람의 승인 검토용 Package와
# 기록 계층 — 자동 승인 시스템 아님). 실제 Promotion Commit/Candidate
# Lifecycle 변경/Runtime 등록은 전혀 수행하지 않는다.
# ---------------------------------------------------------------------------


class CreateDecisionPackageBody(BaseModel):
    explainability_report_id: int
    quality_gate_report_id: int | None = None
    parameter_sensitivity_report_id: int | None = None
    monte_carlo_report_id: int | None = None
    portfolio_validation_report_id: int | None = None
    package_note: str | None = Field(default=None, max_length=2000)
    idempotency_key: str | None = Field(default=None, max_length=64)


class RecordHumanDecisionBody(BaseModel):
    decision_type: str
    reason_code: str
    reason_text: str = Field(min_length=1, max_length=2000)
    checklist_confirmations: dict[str, bool] = Field(default_factory=dict)
    acknowledged_warnings: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=64)


_DECISION_PACKAGE_ERROR_STATUS = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "QUALITY_GATE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "SENSITIVITY_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "MONTE_CARLO_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "PORTFOLIO_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "OWNERSHIP_MISMATCH": status.HTTP_409_CONFLICT,
    "REPORT_ID_MISMATCH": status.HTTP_409_CONFLICT,
    "DEFINITION_NOT_READY": status.HTTP_409_CONFLICT,
    "STALE_PACKAGE": status.HTTP_409_CONFLICT,
    "PACKAGE_NOT_READY": status.HTTP_409_CONFLICT,
    "BLOCKING_EVIDENCE_EXISTS": status.HTTP_409_CONFLICT,
    "INCOMPLETE_CHECKLIST": status.HTTP_409_CONFLICT,
    "WARNINGS_NOT_ACKNOWLEDGED": status.HTTP_409_CONFLICT,
    "DUPLICATE_DECISION": status.HTTP_409_CONFLICT,
    "UNSUPPORTED_DECISION_TYPE": status.HTTP_400_BAD_REQUEST,
    "INVALID_REASON_CODE": status.HTTP_400_BAD_REQUEST,
    "REASON_TEXT_REQUIRED": status.HTTP_400_BAD_REQUEST,
    "IDEMPOTENCY_CONFLICT": status.HTTP_409_CONFLICT,
}


def _decision_package_error_status(code: str) -> int:
    return _DECISION_PACKAGE_ERROR_STATUS.get(code, status.HTTP_400_BAD_REQUEST)


@router.post("/{strategy_id}/decision-packages", status_code=status.HTTP_201_CREATED)
def create_decision_package(
    strategy_id: int,
    body: CreateDecisionPackageBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="DECISION_PACKAGE_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"explainability_report_id": body.explainability_report_id},
    )
    session.commit()
    try:
        result = run_create_decision_package(
            session, strategy_id,
            explainability_report_id=body.explainability_report_id,
            quality_gate_report_id=body.quality_gate_report_id,
            parameter_sensitivity_report_id=body.parameter_sensitivity_report_id,
            monte_carlo_report_id=body.monte_carlo_report_id,
            portfolio_validation_report_id=body.portfolio_validation_report_id,
            package_note=body.package_note, actor=actor, idempotency_key=body.idempotency_key,
        )
    except DecisionPackageError as exc:
        audit.record(
            event_type="DECISION_PACKAGE_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(
            status_code=_decision_package_error_status(exc.code), detail={"code": exc.code, "message": exc.message}
        )

    audit.record(
        event_type="DECISION_PACKAGE_COMPLETED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"package_id": result["package_id"], "package_status": result["package_status"]},
    )
    session.commit()
    return {
        "package_id": result["package_id"],
        "package_status": result["package_status"],
        "readiness_summary": {
            "required_evidence_complete": result["required_evidence_complete"],
            "blocking_evidence_count": result["blocking_evidence_count"],
            "warning_evidence_count": result["warning_evidence_count"],
            "missing_evidence_count": result["missing_evidence_count"],
        },
        "stale": result["stale"],
        "idempotent_replay": result["idempotent_replay"],
    }


def _record_package_viewed(
    audit: AuditLogService, *, actor: str, request_id, strategy_id: int, package_id: int, view: str
) -> None:
    audit.record(
        event_type="DECISION_PACKAGE_VIEWED", actor=actor, request_id=request_id, strategy_id=str(strategy_id),
        detail={"package_id": package_id, "view": view},
    )


@router.get("/{strategy_id}/decision-packages/{package_id}")
def get_decision_package(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_decision_package_report(session, package_id, strategy_definition_id=strategy_id)
    except DecisionPackageError as exc:
        raise HTTPException(status_code=_decision_package_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    _record_package_viewed(
        audit, actor=user.username, request_id=getattr(http_request.state, "request_id", None),
        strategy_id=strategy_id, package_id=package_id, view="detail",
    )
    session.commit()
    return result


@router.get("/{strategy_id}/decision-packages/{package_id}/summary")
def get_decision_package_summary_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_decision_package_summary(session, package_id, strategy_definition_id=strategy_id)
    except DecisionPackageError as exc:
        raise HTTPException(status_code=_decision_package_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    _record_package_viewed(
        audit, actor=user.username, request_id=getattr(http_request.state, "request_id", None),
        strategy_id=strategy_id, package_id=package_id, view="summary",
    )
    session.commit()
    return result


@router.get("/{strategy_id}/decision-packages/{package_id}/checklist")
def get_decision_package_checklist_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_decision_package_checklist(session, package_id, strategy_definition_id=strategy_id)
    except DecisionPackageError as exc:
        raise HTTPException(status_code=_decision_package_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    _record_package_viewed(
        audit, actor=user.username, request_id=getattr(http_request.state, "request_id", None),
        strategy_id=strategy_id, package_id=package_id, view="checklist",
    )
    session.commit()
    return result


@router.get("/{strategy_id}/decision-packages/{package_id}/staleness")
def get_decision_package_staleness_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_decision_package_staleness(session, package_id, strategy_definition_id=strategy_id)
    except DecisionPackageError as exc:
        raise HTTPException(status_code=_decision_package_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="DECISION_PACKAGE_STALENESS_CHECKED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"package_id": package_id, "stale": result["stale"]},
    )
    session.commit()
    return result


@router.post("/{strategy_id}/decision-packages/{package_id}/decisions", status_code=status.HTTP_201_CREATED)
def create_human_decision(
    strategy_id: int, package_id: int, body: RecordHumanDecisionBody, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="HUMAN_DECISION_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"package_id": package_id, "decision_type": body.decision_type},
    )
    session.commit()
    try:
        result = run_record_human_decision(
            session, strategy_id, package_id,
            decision_type=body.decision_type, reason_code=body.reason_code, reason_text=body.reason_text,
            checklist_confirmations=body.checklist_confirmations, acknowledged_warnings=body.acknowledged_warnings,
            actor=actor, idempotency_key=body.idempotency_key,
        )
    except DecisionPackageError as exc:
        audit.record(
            event_type="HUMAN_DECISION_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"package_id": package_id, "code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(
            status_code=_decision_package_error_status(exc.code), detail={"code": exc.code, "message": exc.message}
        )

    decision_event = {
        "APPROVE_FOR_PROMOTION": "HUMAN_DECISION_APPROVED_FOR_PROMOTION",
        "REQUEST_CHANGES": "HUMAN_DECISION_CHANGES_REQUESTED",
        "REJECT": "HUMAN_DECISION_REJECTED",
    }[body.decision_type]
    audit.record(
        event_type=decision_event, actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={
            "package_id": package_id, "decision_id": result["decision_id"], "reason_code": result["reason_code"],
            "same_actor_warning": result["same_actor_warning"],
        },
    )
    session.commit()
    return {
        "decision_id": result["decision_id"],
        "decision_type": result["decision_type"],
        "promotion_ready": result["promotion_ready"],
        "same_actor_warning": result["same_actor_warning"],
        "idempotent_replay": result["idempotent_replay"],
    }


@router.get("/{strategy_id}/decision-packages/{package_id}/decision")
def get_decision_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_human_decision(session, package_id, strategy_definition_id=strategy_id)
    except DecisionPackageError as exc:
        raise HTTPException(status_code=_decision_package_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="HUMAN_DECISION_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"package_id": package_id, "decision_id": result["decision_id"]},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/promotion-readiness")
def get_promotion_readiness_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = get_promotion_readiness(session, strategy_id)
    audit.record(
        event_type="PROMOTION_READINESS_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"ready": result["ready"]},
    )
    session.commit()
    return result


# ---------------------------------------------------------------------------
# STEP12-16 — Promotion Commit(사람의 명시적 승인 이후 Candidate 단계에서
# Promoted 단계로 이동했다는 불변 기록). Activation/Deployment/Runtime
# 등록/Scheduler/Broker/Order/Paper·Live Trading은 전혀 수행하지 않는다.
# ---------------------------------------------------------------------------


class CreatePromotionCommitBody(BaseModel):
    decision_package_id: int
    human_decision_id: int
    promotion_readiness_hash: str
    commit_reason: str = Field(min_length=1, max_length=2000)
    confirmation_text: str
    acknowledge_same_actor_warning: bool = False
    idempotency_key: str | None = Field(default=None, max_length=64)


_PROMOTION_COMMIT_ERROR_STATUS = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "PACKAGE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "DECISION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "OWNERSHIP_MISMATCH": status.HTTP_409_CONFLICT,
    "DECISION_TYPE_MISMATCH": status.HTTP_409_CONFLICT,
    "PROMOTION_NOT_READY": status.HTTP_409_CONFLICT,
    "READINESS_HASH_MISMATCH": status.HTTP_409_CONFLICT,
    "SAME_ACTOR_WARNING_NOT_ACKNOWLEDGED": status.HTTP_409_CONFLICT,
    "ALREADY_PROMOTED": status.HTTP_409_CONFLICT,
    "DUPLICATE_PROMOTION_COMMIT": status.HTTP_409_CONFLICT,
    "STALE_PROMOTION_READINESS": status.HTTP_409_CONFLICT,
    "BLOCKING_EVIDENCE_EXISTS": status.HTTP_409_CONFLICT,
    "PACKAGE_NOT_PROMOTABLE": status.HTTP_409_CONFLICT,
    "LIFECYCLE_NOT_PROMOTABLE": status.HTTP_409_CONFLICT,
    "PROMOTION_STATE_NOT_ELIGIBLE": status.HTTP_409_CONFLICT,
    "INVALID_PROMOTION_STATE_TRANSITION": status.HTTP_409_CONFLICT,
    "DUPLICATE_PROMOTION_HISTORY": status.HTTP_409_CONFLICT,
    "INVALID_CONFIRMATION": status.HTTP_400_BAD_REQUEST,
    "COMMIT_REASON_REQUIRED": status.HTTP_400_BAD_REQUEST,
    "IDEMPOTENCY_CONFLICT": status.HTTP_409_CONFLICT,
}


def _promotion_commit_error_status(code: str) -> int:
    return _PROMOTION_COMMIT_ERROR_STATUS.get(code, status.HTTP_400_BAD_REQUEST)


@router.post("/{strategy_id}/promotion-commits", status_code=status.HTTP_201_CREATED)
def create_promotion_commit(
    strategy_id: int, body: CreatePromotionCommitBody, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="PROMOTION_COMMIT_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"decision_package_id": body.decision_package_id, "human_decision_id": body.human_decision_id},
    )
    session.commit()
    try:
        result = run_create_promotion_commit(
            session, strategy_id,
            decision_package_id=body.decision_package_id, human_decision_id=body.human_decision_id,
            promotion_readiness_hash=body.promotion_readiness_hash, commit_reason=body.commit_reason,
            confirmation_text=body.confirmation_text,
            acknowledge_same_actor_warning=body.acknowledge_same_actor_warning,
            actor=actor, idempotency_key=body.idempotency_key,
        )
    except PromotionCommitError as exc:
        audit.record(
            event_type="PROMOTION_COMMIT_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        if exc.code in {"PROMOTION_STATE_NOT_ELIGIBLE", "INVALID_PROMOTION_STATE_TRANSITION", "ALREADY_PROMOTED"}:
            audit.record(
                event_type="PROMOTION_STATE_TRANSITION_FAILED", actor=actor,
                request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
                detail={"code": exc.code, "message": exc.message},
            )
        session.commit()
        raise HTTPException(
            status_code=_promotion_commit_error_status(exc.code), detail={"code": exc.code, "message": exc.message}
        )

    audit.record(
        event_type="PROMOTION_COMMIT_COMPLETED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={
            "promotion_commit_id": result["promotion_commit_id"],
            "promotion_commit_hash": result["promotion_commit_hash"],
            "previous_promotion_status": result["previous_promotion_status"],
            "new_promotion_status": result["current_promotion_status"],
            "candidate_lifecycle_status": result["candidate_lifecycle_status"],
            "human_decision_id": result["human_decision_id"],
        },
    )
    if not result["idempotent_replay"]:
        audit.record(
            event_type="PROMOTION_STATE_TRANSITIONED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={
                "promotion_commit_id": result["promotion_commit_id"],
                "previous_promotion_status": result["previous_promotion_status"],
                "new_promotion_status": result["current_promotion_status"],
                "candidate_lifecycle_status": result["candidate_lifecycle_status"],
                "human_decision_id": result["human_decision_id"],
            },
        )
    session.commit()
    return {
        "promotion_commit_id": result["promotion_commit_id"],
        "promotion_committed": result["promotion_committed"],
        # § STEP12-16R — 실제 전이시킨 적 없는 "lifecycle" 표현은 제거하고
        # Candidate Lifecycle과 Strategy Promotion Status를 분리해 노출한다.
        "strategy_promotion_status": result["strategy_promotion_status"],
        "candidate_lifecycle_status": result["candidate_lifecycle_status"],
        "previous_promotion_status": result["previous_promotion_status"],
        "current_promotion_status": result["current_promotion_status"],
        "promotion_state_version": result["promotion_state_version"],
        "promotion_commit_hash": result["promotion_commit_hash"],
        "committed_by": result["committed_by"],
        "committed_at": result["committed_at"],
        "activation_status": result["activation_status"],
        "deployment_status": result["deployment_status"],
        "runtime_status": result["runtime_status"],
        "next_action": result["next_action"],
        "idempotent_replay": result["idempotent_replay"],
    }


@router.get("/{strategy_id}/promotion-commits")
def list_promotion_commits_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = list_promotion_commits(session, strategy_id)
    audit.record(
        event_type="PROMOTION_COMMIT_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "list", "count": len(result)},
    )
    session.commit()
    return {"strategy_id": strategy_id, "commits": result}


@router.get("/{strategy_id}/promotion-commits/{commit_id}")
def get_promotion_commit_endpoint(
    strategy_id: int, commit_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_promotion_commit(session, commit_id, strategy_definition_id=strategy_id)
    except PromotionCommitError as exc:
        raise HTTPException(status_code=_promotion_commit_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="PROMOTION_COMMIT_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "detail", "promotion_commit_id": commit_id},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/promotion-status")
def get_promotion_status_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = get_promotion_status(session, strategy_id)
    audit.record(
        event_type="PROMOTION_STATUS_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"promotion_committed": result["promotion_committed"]},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/promotion-commits/{commit_id}/provenance")
def get_promotion_commit_provenance_endpoint(
    strategy_id: int, commit_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_promotion_commit_provenance(session, commit_id, strategy_definition_id=strategy_id)
    except PromotionCommitError as exc:
        raise HTTPException(status_code=_promotion_commit_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="PROMOTION_PROVENANCE_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"promotion_commit_id": commit_id},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/promotion-commits/{commit_id}/history")
def get_promotion_commit_history_endpoint(
    strategy_id: int, commit_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        get_promotion_commit(session, commit_id, strategy_definition_id=strategy_id)
    except PromotionCommitError as exc:
        raise HTTPException(status_code=_promotion_commit_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    result = get_promotion_commit_history(session, strategy_id)
    audit.record(
        event_type="PROMOTION_HISTORY_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"promotion_commit_id": commit_id},
    )
    session.commit()
    return result


# ---------------------------------------------------------------------------
# STEP 12-17 — Activation Review Package / Human Activation Decision /
# Activation Commit. Runtime 등록/시작, Scheduler 등록, Broker 연결,
# 주문 실행은 전혀 수행하지 않는다.
# ---------------------------------------------------------------------------


class CreateActivationReviewPackageBody(BaseModel):
    promotion_commit_id: int
    target_market_type: str
    target_broker_code: str
    target_account_kind: str
    target_user_broker_account_id: int | None = None
    target_paper_account_id: int | None = None
    requested_execution_mode: str
    requested_runtime_scope: dict[str, Any] | None = None
    requested_capital_limit: str | None = None
    review_note: str | None = Field(default=None, max_length=2000)
    idempotency_key: str | None = Field(default=None, max_length=64)


class RecordActivationDecisionBody(BaseModel):
    decision_type: str
    reason_code: str
    reason_text: str = Field(min_length=1, max_length=2000)
    checklist_confirmations: dict[str, bool] = Field(default_factory=dict)
    acknowledged_warnings: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=64)


class CreateActivationCommitBody(BaseModel):
    activation_review_package_id: int
    activation_decision_id: int
    activation_readiness_hash: str
    commit_reason: str = Field(min_length=1, max_length=2000)
    confirmation_text: str
    acknowledge_same_actor_warning: bool = False
    idempotency_key: str | None = Field(default=None, max_length=64)


_ACTIVATION_ERROR_STATUS: dict[str, int] = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "PACKAGE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "DECISION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "OWNERSHIP_MISMATCH": status.HTTP_409_CONFLICT,
    "PROMOTION_NOT_COMMITTED": status.HTTP_409_CONFLICT,
    "ALREADY_ACTIVATED": status.HTTP_409_CONFLICT,
    "ALREADY_UNDER_REVIEW": status.HTTP_409_CONFLICT,
    "STRATEGY_NOT_ELIGIBLE": status.HTTP_409_CONFLICT,
    "INVALID_EXECUTION_MODE": status.HTTP_400_BAD_REQUEST,
    "INVALID_ACCOUNT_KIND": status.HTTP_400_BAD_REQUEST,
    "INVALID_DECISION_TYPE": status.HTTP_400_BAD_REQUEST,
    "INVALID_REASON_CODE": status.HTTP_400_BAD_REQUEST,
    "REASON_TEXT_REQUIRED": status.HTTP_400_BAD_REQUEST,
    "DUPLICATE_ACTIVATION_DECISION": status.HTTP_409_CONFLICT,
    "STALE_ACTIVATION_PACKAGE": status.HTTP_409_CONFLICT,
    "PACKAGE_NOT_READY": status.HTTP_409_CONFLICT,
    "INCOMPLETE_CHECKLIST": status.HTTP_409_CONFLICT,
    "WARNING_NOT_ACKNOWLEDGED": status.HTTP_409_CONFLICT,
    "DECISION_TYPE_MISMATCH": status.HTTP_409_CONFLICT,
    "ACTIVATION_NOT_READY": status.HTTP_409_CONFLICT,
    "READINESS_HASH_MISMATCH": status.HTTP_409_CONFLICT,
    "SAME_ACTOR_WARNING_NOT_ACKNOWLEDGED": status.HTTP_409_CONFLICT,
    "PROMOTION_STATE_NOT_ELIGIBLE": status.HTTP_409_CONFLICT,
    "INVALID_PROMOTION_STATE_TRANSITION": status.HTTP_409_CONFLICT,
    "DUPLICATE_ACTIVATION_COMMIT": status.HTTP_409_CONFLICT,
    "DUPLICATE_ACTIVATION_HISTORY": status.HTTP_409_CONFLICT,
    "DUPLICATE_ACTIVATION_REVIEW": status.HTTP_409_CONFLICT,
    "IDEMPOTENCY_CONFLICT": status.HTTP_409_CONFLICT,
    "COMMIT_REASON_REQUIRED": status.HTTP_400_BAD_REQUEST,
    "INVALID_CONFIRMATION": status.HTTP_400_BAD_REQUEST,
}


def _activation_error_status(code: str) -> int:
    return _ACTIVATION_ERROR_STATUS.get(code, status.HTTP_400_BAD_REQUEST)


@router.post("/{strategy_id}/activation-review-packages", status_code=status.HTTP_201_CREATED)
def create_activation_review_package(
    strategy_id: int, body: CreateActivationReviewPackageBody, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="ACTIVATION_REVIEW_PACKAGE_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"promotion_commit_id": body.promotion_commit_id, "requested_execution_mode": body.requested_execution_mode},
    )
    session.commit()
    try:
        result = run_create_activation_review_package(
            session, strategy_id,
            promotion_commit_id=body.promotion_commit_id, target_market_type=body.target_market_type,
            target_broker_code=body.target_broker_code, target_account_kind=body.target_account_kind,
            target_user_broker_account_id=body.target_user_broker_account_id,
            target_paper_account_id=body.target_paper_account_id,
            requested_execution_mode=body.requested_execution_mode,
            requested_runtime_scope=body.requested_runtime_scope, requested_capital_limit=body.requested_capital_limit,
            review_note=body.review_note, actor=actor, idempotency_key=body.idempotency_key,
        )
    except ActivationError as exc:
        audit.record(
            event_type="ACTIVATION_REVIEW_PACKAGE_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(status_code=_activation_error_status(exc.code), detail={"code": exc.code, "message": exc.message})

    audit.record(
        event_type="ACTIVATION_REVIEW_PACKAGE_COMPLETED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={
            "activation_review_package_id": result["activation_review_package_id"],
            "readiness_status": result["readiness_status"],
            "blocking_reason_codes": result["blocking_reason_codes"],
        },
    )
    if result["readiness_status"] == "READY_FOR_ACTIVATION_REVIEW" and not result["idempotent_replay"]:
        audit.record(
            event_type="PROMOTION_STATE_TRANSITIONED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={
                "activation_review_package_id": result["activation_review_package_id"],
                "new_promotion_status": "ACTIVATION_REVIEW",
            },
        )
    session.commit()
    return result


@router.get("/{strategy_id}/activation-review-packages")
def list_activation_review_packages_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = list_activation_review_packages(session, strategy_id)
    audit.record(
        event_type="ACTIVATION_REVIEW_PACKAGE_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "list", "count": len(result)},
    )
    session.commit()
    return {"strategy_id": strategy_id, "packages": result}


@router.get("/{strategy_id}/activation-review-packages/{package_id}")
def get_activation_review_package_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_activation_review_package(session, package_id, strategy_definition_id=strategy_id)
    except ActivationError as exc:
        raise HTTPException(status_code=_activation_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="ACTIVATION_REVIEW_PACKAGE_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "detail", "activation_review_package_id": package_id},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/activation-review-packages/{package_id}/summary")
def get_activation_review_package_summary_endpoint(
    strategy_id: int, package_id: int,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
):
    try:
        result = get_activation_review_package(session, package_id, strategy_definition_id=strategy_id)
    except ActivationError as exc:
        raise HTTPException(status_code=_activation_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    return {
        "activation_review_package_id": result["activation_review_package_id"],
        "readiness_status": result["readiness_status"],
        "blocking_reason_codes": result["blocking_reason_codes"],
        "warning_reason_codes": result["warning_reason_codes"],
        "missing_requirement_codes": result["missing_requirement_codes"],
        "requested_execution_mode": result["requested_execution_mode"],
    }


@router.get("/{strategy_id}/activation-review-packages/{package_id}/checklist")
def get_activation_review_package_checklist_endpoint(
    strategy_id: int, package_id: int,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
):
    try:
        get_activation_review_package(session, package_id, strategy_definition_id=strategy_id)
        return get_activation_review_package_checklist(session, package_id)
    except ActivationError as exc:
        raise HTTPException(status_code=_activation_error_status(exc.code), detail={"code": exc.code, "message": exc.message})


@router.get("/{strategy_id}/activation-review-packages/{package_id}/staleness")
def get_activation_review_package_staleness_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        get_activation_review_package(session, package_id, strategy_definition_id=strategy_id)
        result = get_activation_review_package_staleness(session, package_id)
    except ActivationError as exc:
        raise HTTPException(status_code=_activation_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="ACTIVATION_REVIEW_STALENESS_CHECKED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"activation_review_package_id": package_id, "stale": result["stale"]},
    )
    session.commit()
    return result


@router.post("/{strategy_id}/activation-review-packages/{package_id}/decisions", status_code=status.HTTP_201_CREATED)
def record_activation_decision(
    strategy_id: int, package_id: int, body: RecordActivationDecisionBody, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="ACTIVATION_DECISION_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"activation_review_package_id": package_id, "decision_type": body.decision_type},
    )
    session.commit()
    try:
        result = run_record_activation_decision(
            session, strategy_id, package_id,
            decision_type=body.decision_type, reason_code=body.reason_code, reason_text=body.reason_text,
            checklist_confirmations=body.checklist_confirmations, acknowledged_warnings=body.acknowledged_warnings,
            actor=actor, idempotency_key=body.idempotency_key,
        )
    except ActivationError as exc:
        audit.record(
            event_type="ACTIVATION_DECISION_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(status_code=_activation_error_status(exc.code), detail={"code": exc.code, "message": exc.message})

    event_by_type = {
        "APPROVE_ACTIVATION": "ACTIVATION_DECISION_APPROVED",
        "REQUEST_ACTIVATION_CHANGES": "ACTIVATION_DECISION_CHANGES_REQUESTED",
        "REJECT_ACTIVATION": "ACTIVATION_DECISION_REJECTED",
    }
    audit.record(
        event_type=event_by_type.get(body.decision_type, "ACTIVATION_DECISION_APPROVED"), actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"activation_decision_id": result["activation_decision_id"], "activation_ready": result["activation_ready"]},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/activation-review-packages/{package_id}/decision")
def get_activation_decision_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    get_activation_review_package(session, package_id, strategy_definition_id=strategy_id)
    result = get_activation_decision(session, package_id)
    audit.record(
        event_type="ACTIVATION_DECISION_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"activation_review_package_id": package_id},
    )
    session.commit()
    return result


@router.post("/{strategy_id}/activation-commits", status_code=status.HTTP_201_CREATED)
def create_activation_commit(
    strategy_id: int, body: CreateActivationCommitBody, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="ACTIVATION_COMMIT_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={
            "activation_review_package_id": body.activation_review_package_id,
            "activation_decision_id": body.activation_decision_id,
        },
    )
    session.commit()
    try:
        result = run_create_activation_commit(
            session, strategy_id,
            activation_review_package_id=body.activation_review_package_id,
            activation_decision_id=body.activation_decision_id,
            activation_readiness_hash=body.activation_readiness_hash, commit_reason=body.commit_reason,
            confirmation_text=body.confirmation_text,
            acknowledge_same_actor_warning=body.acknowledge_same_actor_warning,
            actor=actor, idempotency_key=body.idempotency_key,
        )
    except ActivationError as exc:
        audit.record(
            event_type="ACTIVATION_COMMIT_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        if exc.code in {"PROMOTION_STATE_NOT_ELIGIBLE", "INVALID_PROMOTION_STATE_TRANSITION", "ALREADY_ACTIVATED"}:
            audit.record(
                event_type="PROMOTION_STATE_TRANSITION_FAILED", actor=actor,
                request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
                detail={"code": exc.code, "message": exc.message},
            )
        session.commit()
        raise HTTPException(status_code=_activation_error_status(exc.code), detail={"code": exc.code, "message": exc.message})

    audit.record(
        event_type="ACTIVATION_COMMIT_COMPLETED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={
            "activation_commit_id": result["activation_commit_id"],
            "activation_commit_hash": result["activation_commit_hash"],
            "previous_promotion_status": result["previous_promotion_status"],
            "new_promotion_status": result["current_promotion_status"],
            "candidate_lifecycle_status": result["candidate_lifecycle_status"],
        },
    )
    if not result["idempotent_replay"]:
        audit.record(
            event_type="PROMOTION_STATE_TRANSITIONED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={
                "activation_commit_id": result["activation_commit_id"],
                "previous_promotion_status": result["previous_promotion_status"],
                "new_promotion_status": result["current_promotion_status"],
            },
        )
    session.commit()
    return result


@router.get("/{strategy_id}/activation-commits")
def list_activation_commits_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = list_activation_commits(session, strategy_id)
    audit.record(
        event_type="ACTIVATION_COMMIT_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "list", "count": len(result)},
    )
    session.commit()
    return {"strategy_id": strategy_id, "commits": result}


@router.get("/{strategy_id}/activation-commits/{commit_id}")
def get_activation_commit_endpoint(
    strategy_id: int, commit_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_activation_commit(session, commit_id, strategy_definition_id=strategy_id)
    except ActivationError as exc:
        raise HTTPException(status_code=_activation_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="ACTIVATION_COMMIT_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "detail", "activation_commit_id": commit_id},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/activation-status")
def get_activation_status_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = get_activation_status(session, strategy_id)
    audit.record(
        event_type="ACTIVATION_STATUS_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"activation_committed": result["activation_committed"]},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/activation-commits/{commit_id}/provenance")
def get_activation_commit_provenance_endpoint(
    strategy_id: int, commit_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_activation_commit_provenance(session, commit_id, strategy_definition_id=strategy_id)
    except ActivationError as exc:
        raise HTTPException(status_code=_activation_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="ACTIVATION_PROVENANCE_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"activation_commit_id": commit_id},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/activation-commits/{commit_id}/history")
def get_activation_commit_history_endpoint(
    strategy_id: int, commit_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        get_activation_commit(session, commit_id, strategy_definition_id=strategy_id)
    except ActivationError as exc:
        raise HTTPException(status_code=_activation_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    # § 명세 "Promotion History는 기존 strategy_promotion_history 재사용" —
    # Activation 전이도 같은 History 테이블에 기록되므로 동일 조회 함수를
    # 재사용한다(Promotion Commit + Activation Review + Activation Commit
    # 전이 전체가 하나의 통합 History로 조회된다).
    result = get_promotion_commit_history(session, strategy_id)
    audit.record(
        event_type="ACTIVATION_HISTORY_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"activation_commit_id": commit_id},
    )
    session.commit()
    return result


# ---------------------------------------------------------------------------
# STEP 12-18 — Runtime Registration Review Package / Human Runtime
# Registration Decision / Runtime Registration Commit. Runtime 시작,
# Scheduler 등록, Broker 연결/로그인, 실시간 시세 구독, Signal 계산, 주문
# 생성/전송은 전혀 수행하지 않는다.
# ---------------------------------------------------------------------------


class CreateRuntimeRegistrationPackageBody(BaseModel):
    activation_commit_id: int
    activation_decision_id: int
    target_account_kind: str
    target_user_broker_account_id: int | None = None
    target_paper_account_id: int | None = None
    target_market_type: str
    target_broker_code: str
    execution_mode: str
    idempotency_key: str | None = Field(default=None, max_length=64)


class RecordRuntimeRegistrationDecisionBody(BaseModel):
    decision_type: str
    reason_code: str
    reason_text: str = Field(min_length=1, max_length=2000)
    checklist_confirmations: dict[str, bool] = Field(default_factory=dict)
    acknowledged_warnings: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=64)


class CreateRuntimeRegistrationCommitBody(BaseModel):
    runtime_registration_package_id: int
    runtime_registration_decision_id: int
    registration_input_hash: str
    decision_input_hash: str
    commit_reason: str = Field(min_length=1, max_length=2000)
    confirmation_text: str
    acknowledge_same_actor_warning: bool = False
    idempotency_key: str | None = Field(default=None, max_length=64)


_RUNTIME_REGISTRATION_ERROR_STATUS: dict[str, int] = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "PACKAGE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "DECISION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "ACTIVATION_COMMIT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "OWNERSHIP_MISMATCH": status.HTTP_409_CONFLICT,
    "STRATEGY_NOT_ACTIVATED": status.HTTP_409_CONFLICT,
    "ALREADY_REGISTERED": status.HTTP_409_CONFLICT,
    "INVALID_EXECUTION_MODE": status.HTTP_400_BAD_REQUEST,
    "INVALID_ACCOUNT_KIND": status.HTTP_400_BAD_REQUEST,
    "INVALID_DECISION_TYPE": status.HTTP_400_BAD_REQUEST,
    "INVALID_REASON_CODE": status.HTTP_400_BAD_REQUEST,
    "REASON_TEXT_REQUIRED": status.HTTP_400_BAD_REQUEST,
    "DUPLICATE_RUNTIME_REGISTRATION_DECISION": status.HTTP_409_CONFLICT,
    "DUPLICATE_RUNTIME_REGISTRATION_COMMIT": status.HTTP_409_CONFLICT,
    "STALE_RUNTIME_REGISTRATION_PACKAGE": status.HTTP_409_CONFLICT,
    "PACKAGE_NOT_READY": status.HTTP_409_CONFLICT,
    "INCOMPLETE_CHECKLIST": status.HTTP_409_CONFLICT,
    "WARNING_NOT_ACKNOWLEDGED": status.HTTP_409_CONFLICT,
    "DECISION_TYPE_MISMATCH": status.HTTP_409_CONFLICT,
    "REGISTRATION_NOT_READY": status.HTTP_409_CONFLICT,
    "READINESS_HASH_MISMATCH": status.HTTP_409_CONFLICT,
    "SAME_ACTOR_WARNING_NOT_ACKNOWLEDGED": status.HTTP_409_CONFLICT,
    "IDEMPOTENCY_CONFLICT": status.HTTP_409_CONFLICT,
    "COMMIT_REASON_REQUIRED": status.HTTP_400_BAD_REQUEST,
    "INVALID_CONFIRMATION": status.HTTP_400_BAD_REQUEST,
    "DUPLICATE_RUNTIME_REGISTRATION_REVIEW": status.HTTP_409_CONFLICT,
    "DUPLICATE_RUNTIME_REGISTRATION_HISTORY": status.HTTP_409_CONFLICT,
    "RUNTIME_SCOPE_ALREADY_REGISTERED": status.HTTP_409_CONFLICT,
}


def _runtime_registration_error_status(code: str) -> int:
    return _RUNTIME_REGISTRATION_ERROR_STATUS.get(code, status.HTTP_400_BAD_REQUEST)


@router.post("/{strategy_id}/runtime-registration-packages", status_code=status.HTTP_201_CREATED)
def create_runtime_registration_package(
    strategy_id: int, body: CreateRuntimeRegistrationPackageBody, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="RUNTIME_REGISTRATION_PACKAGE_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"activation_commit_id": body.activation_commit_id, "execution_mode": body.execution_mode},
    )
    session.commit()
    try:
        result = run_create_runtime_registration_package(
            session, strategy_id,
            activation_commit_id=body.activation_commit_id, activation_decision_id=body.activation_decision_id,
            target_account_kind=body.target_account_kind,
            target_user_broker_account_id=body.target_user_broker_account_id,
            target_paper_account_id=body.target_paper_account_id, target_market_type=body.target_market_type,
            target_broker_code=body.target_broker_code, execution_mode=body.execution_mode,
            actor=actor, idempotency_key=body.idempotency_key,
        )
    except RuntimeRegistrationError as exc:
        audit.record(
            event_type="RUNTIME_REGISTRATION_PACKAGE_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(status_code=_runtime_registration_error_status(exc.code), detail={"code": exc.code, "message": exc.message})

    audit.record(
        event_type="RUNTIME_REGISTRATION_PACKAGE_COMPLETED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={
            "runtime_registration_package_id": result["runtime_registration_package_id"],
            "registration_readiness_status": result["registration_readiness_status"],
            "blocking_reason_codes": result["blocking_reason_codes"],
        },
    )
    session.commit()
    return result


@router.get("/{strategy_id}/runtime-registration-packages")
def list_runtime_registration_packages_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = list_runtime_registration_packages(session, strategy_id)
    audit.record(
        event_type="RUNTIME_REGISTRATION_PACKAGE_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "list", "count": len(result)},
    )
    session.commit()
    return {"strategy_id": strategy_id, "packages": result}


@router.get("/{strategy_id}/runtime-registration-packages/{package_id}")
def get_runtime_registration_package_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_runtime_registration_package(session, package_id, strategy_definition_id=strategy_id)
    except RuntimeRegistrationError as exc:
        raise HTTPException(status_code=_runtime_registration_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="RUNTIME_REGISTRATION_PACKAGE_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "detail", "runtime_registration_package_id": package_id},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/runtime-registration-packages/{package_id}/summary")
def get_runtime_registration_package_summary_endpoint(
    strategy_id: int, package_id: int,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
):
    try:
        result = get_runtime_registration_package(session, package_id, strategy_definition_id=strategy_id)
    except RuntimeRegistrationError as exc:
        raise HTTPException(status_code=_runtime_registration_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    return {
        "runtime_registration_package_id": result["runtime_registration_package_id"],
        "created_readiness_status": result["created_readiness_status"],
        "current_effective_status": result["current_effective_status"],
        "blocking_reason_codes": result["blocking_reason_codes"],
        "warning_reason_codes": result["warning_reason_codes"],
        "missing_requirement_codes": result["missing_requirement_codes"],
        "execution_mode": result["execution_mode"],
    }


@router.get("/{strategy_id}/runtime-registration-packages/{package_id}/checklist")
def get_runtime_registration_package_checklist_endpoint(
    strategy_id: int, package_id: int,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
):
    try:
        get_runtime_registration_package(session, package_id, strategy_definition_id=strategy_id)
        return get_runtime_registration_package_checklist(session, package_id)
    except RuntimeRegistrationError as exc:
        raise HTTPException(status_code=_runtime_registration_error_status(exc.code), detail={"code": exc.code, "message": exc.message})


@router.get("/{strategy_id}/runtime-registration-packages/{package_id}/staleness")
def get_runtime_registration_package_staleness_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        get_runtime_registration_package(session, package_id, strategy_definition_id=strategy_id)
        result = get_runtime_registration_package_staleness(session, package_id)
    except RuntimeRegistrationError as exc:
        raise HTTPException(status_code=_runtime_registration_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="RUNTIME_REGISTRATION_STALENESS_CHECKED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"runtime_registration_package_id": package_id, "stale": result["stale"]},
    )
    session.commit()
    return result


@router.post("/{strategy_id}/runtime-registration-packages/{package_id}/decisions", status_code=status.HTTP_201_CREATED)
def record_runtime_registration_decision(
    strategy_id: int, package_id: int, body: RecordRuntimeRegistrationDecisionBody, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="RUNTIME_REGISTRATION_DECISION_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"runtime_registration_package_id": package_id, "decision_type": body.decision_type},
    )
    session.commit()
    try:
        result = run_record_runtime_registration_decision(
            session, strategy_id, package_id,
            decision_type=body.decision_type, reason_code=body.reason_code, reason_text=body.reason_text,
            checklist_confirmations=body.checklist_confirmations, acknowledged_warnings=body.acknowledged_warnings,
            actor=actor, idempotency_key=body.idempotency_key,
        )
    except RuntimeRegistrationError as exc:
        audit.record(
            event_type="RUNTIME_REGISTRATION_DECISION_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(status_code=_runtime_registration_error_status(exc.code), detail={"code": exc.code, "message": exc.message})

    event_by_type = {
        "APPROVE_RUNTIME_REGISTRATION": "RUNTIME_REGISTRATION_DECISION_APPROVED",
        "REQUEST_RUNTIME_REGISTRATION_CHANGES": "RUNTIME_REGISTRATION_DECISION_CHANGES_REQUESTED",
        "REJECT_RUNTIME_REGISTRATION": "RUNTIME_REGISTRATION_DECISION_REJECTED",
    }
    audit.record(
        event_type=event_by_type.get(body.decision_type, "RUNTIME_REGISTRATION_DECISION_APPROVED"), actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"runtime_registration_decision_id": result["runtime_registration_decision_id"], "registration_ready": result["registration_ready"]},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/runtime-registration-packages/{package_id}/decision")
def get_runtime_registration_decision_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    get_runtime_registration_package(session, package_id, strategy_definition_id=strategy_id)
    result = get_runtime_registration_decision(session, package_id)
    audit.record(
        event_type="RUNTIME_REGISTRATION_DECISION_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"runtime_registration_package_id": package_id},
    )
    session.commit()
    return result


@router.post("/{strategy_id}/runtime-registration-commits", status_code=status.HTTP_201_CREATED)
def create_runtime_registration_commit(
    strategy_id: int, body: CreateRuntimeRegistrationCommitBody, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="RUNTIME_REGISTRATION_COMMIT_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={
            "runtime_registration_package_id": body.runtime_registration_package_id,
            "runtime_registration_decision_id": body.runtime_registration_decision_id,
        },
    )
    session.commit()
    try:
        result = run_create_runtime_registration_commit(
            session, strategy_id,
            runtime_registration_package_id=body.runtime_registration_package_id,
            runtime_registration_decision_id=body.runtime_registration_decision_id,
            registration_input_hash=body.registration_input_hash, decision_input_hash=body.decision_input_hash,
            commit_reason=body.commit_reason, confirmation_text=body.confirmation_text,
            acknowledge_same_actor_warning=body.acknowledge_same_actor_warning,
            actor=actor, idempotency_key=body.idempotency_key,
        )
    except RuntimeRegistrationError as exc:
        audit.record(
            event_type="RUNTIME_REGISTRATION_COMMIT_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(status_code=_runtime_registration_error_status(exc.code), detail={"code": exc.code, "message": exc.message})

    # § STEP12-18R — 완료 Audit("RUNTIME_REGISTERED")는 더 이상 여기서
    # 별도로 기록하지 않는다. `run_create_runtime_registration_commit()`
    # 내부에서 Commit/Registry/AccountStrategyLink/History와 같은
    # Transaction으로(`AuditLogService.record()`의 내부 commit을 그 전체의
    # 단일 원자적 커밋 지점으로 삼아) 이미 기록했다 — 여기서 다시 쓰면
    # "완료 후에야 기록되는" 비원자적 Audit가 되어 실패 시 Rollback되지
    # 않는 이전 설계로 되돌아간다.
    return result


@router.get("/{strategy_id}/runtime-registration-commits")
def list_runtime_registration_commits_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = list_runtime_registration_commits(session, strategy_id)
    audit.record(
        event_type="RUNTIME_REGISTRATION_COMMIT_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "list", "count": len(result)},
    )
    session.commit()
    return {"strategy_id": strategy_id, "commits": result}


@router.get("/{strategy_id}/runtime-registration-commits/{commit_id}")
def get_runtime_registration_commit_endpoint(
    strategy_id: int, commit_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_runtime_registration_commit(session, commit_id, strategy_definition_id=strategy_id)
    except RuntimeRegistrationError as exc:
        raise HTTPException(status_code=_runtime_registration_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="RUNTIME_REGISTRATION_COMMIT_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "detail", "runtime_registration_commit_id": commit_id},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/runtime-registration-status")
def get_runtime_registration_status_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = get_runtime_registration_status(session, strategy_id)
    audit.record(
        event_type="RUNTIME_REGISTRATION_STATUS_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"registered": result["registered"]},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/runtime-registration-history")
def get_runtime_registration_history_endpoint(
    strategy_id: int, http_request: Request,
    runtime_scope_hash: str | None = None, runtime_registration_commit_id: int | None = None,
    account_id: int | None = None, execution_mode: str | None = None,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = get_runtime_registration_history(
        session, strategy_id, runtime_scope_hash=runtime_scope_hash,
        runtime_registration_commit_id=runtime_registration_commit_id, account_id=account_id,
        execution_mode=execution_mode,
    )
    audit.record(
        event_type="RUNTIME_REGISTRATION_HISTORY_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"count": len(result), "runtime_scope_hash": runtime_scope_hash},
    )
    session.commit()
    return {"strategy_id": strategy_id, "history": result}


@router.get("/{strategy_id}/runtime-registration-scopes")
def get_runtime_registration_scopes_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = get_runtime_registration_scopes(session, strategy_id)
    audit.record(
        event_type="RUNTIME_REGISTRATION_STATUS_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "scopes", "count": len(result)},
    )
    session.commit()
    return {"strategy_id": strategy_id, "scopes": result}


@router.get("/{strategy_id}/runtime-registration-commits/{commit_id}/provenance")
def get_runtime_registration_commit_provenance_endpoint(
    strategy_id: int, commit_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_runtime_registration_commit_provenance(session, commit_id, strategy_definition_id=strategy_id)
    except RuntimeRegistrationError as exc:
        raise HTTPException(status_code=_runtime_registration_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="RUNTIME_REGISTRATION_PROVENANCE_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"runtime_registration_commit_id": commit_id},
    )
    session.commit()
    return result


# ---------------------------------------------------------------------------
# STEP 12-19 — Runtime Deployment Readiness & Disabled Scheduler Plan
# ---------------------------------------------------------------------------


class CreateDeploymentReadinessPackageBody(BaseModel):
    runtime_registration_commit_id: int
    runtime_registry_id: int
    idempotency_key: str | None = Field(default=None, max_length=64)


class RecordDeploymentReadinessDecisionBody(BaseModel):
    decision_type: str
    reason_code: str
    reason_text: str = Field(min_length=1, max_length=2000)
    checklist_confirmations: dict[str, bool] = Field(default_factory=dict)
    acknowledged_warnings: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=64)


class CreateDeploymentReadinessCommitBody(BaseModel):
    deployment_readiness_package_id: int
    deployment_readiness_decision_id: int
    runtime_registration_commit_id: int
    runtime_scope_hash: str
    deployment_input_hash: str
    decision_input_hash: str
    commit_reason: str = Field(min_length=1, max_length=2000)
    confirmation_text: str
    acknowledge_same_actor_warning: bool = False
    idempotency_key: str | None = Field(default=None, max_length=64)


_DEPLOYMENT_READINESS_ERROR_STATUS: dict[str, int] = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "PACKAGE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "DECISION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "RUNTIME_REGISTRATION_COMMIT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "RUNTIME_REGISTRY_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "RUNTIME_SCOPE_MISMATCH": status.HTTP_409_CONFLICT,
    "OWNERSHIP_MISMATCH": status.HTTP_409_CONFLICT,
    "STRATEGY_NOT_ACTIVATED": status.HTTP_409_CONFLICT,
    "DEPLOYMENT_ALREADY_EXISTS": status.HTTP_409_CONFLICT,
    "SCHEDULER_PLAN_ALREADY_EXISTS": status.HTTP_409_CONFLICT,
    "INVALID_DECISION_TYPE": status.HTTP_400_BAD_REQUEST,
    "INVALID_REASON_CODE": status.HTTP_400_BAD_REQUEST,
    "REASON_TEXT_REQUIRED": status.HTTP_400_BAD_REQUEST,
    "DUPLICATE_DEPLOYMENT_READINESS_REVIEW": status.HTTP_409_CONFLICT,
    "DUPLICATE_DEPLOYMENT_READINESS_DECISION": status.HTTP_409_CONFLICT,
    "DUPLICATE_DEPLOYMENT_READINESS_COMMIT": status.HTTP_409_CONFLICT,
    "DUPLICATE_DEPLOYMENT_READINESS_HISTORY": status.HTTP_409_CONFLICT,
    "STALE_DEPLOYMENT_READINESS_PACKAGE": status.HTTP_409_CONFLICT,
    "PACKAGE_NOT_READY": status.HTTP_409_CONFLICT,
    "INCOMPLETE_CHECKLIST": status.HTTP_409_CONFLICT,
    "WARNING_NOT_ACKNOWLEDGED": status.HTTP_409_CONFLICT,
    "DECISION_TYPE_MISMATCH": status.HTTP_409_CONFLICT,
    "DEPLOYMENT_NOT_READY": status.HTTP_409_CONFLICT,
    "READINESS_HASH_MISMATCH": status.HTTP_409_CONFLICT,
    "SAME_ACTOR_WARNING_NOT_ACKNOWLEDGED": status.HTTP_409_CONFLICT,
    "IDEMPOTENCY_CONFLICT": status.HTTP_409_CONFLICT,
    "COMMIT_REASON_REQUIRED": status.HTTP_400_BAD_REQUEST,
    "INVALID_CONFIRMATION": status.HTTP_400_BAD_REQUEST,
}


def _deployment_readiness_error_status(code: str) -> int:
    return _DEPLOYMENT_READINESS_ERROR_STATUS.get(code, status.HTTP_400_BAD_REQUEST)


@router.post("/{strategy_id}/deployment-readiness-packages", status_code=status.HTTP_201_CREATED)
def create_deployment_readiness_package(
    strategy_id: int, body: CreateDeploymentReadinessPackageBody, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="DEPLOYMENT_READINESS_PACKAGE_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={
            "runtime_registration_commit_id": body.runtime_registration_commit_id,
            "runtime_registry_id": body.runtime_registry_id,
        },
    )
    session.commit()
    try:
        result = run_create_deployment_readiness_package(
            session, strategy_id,
            runtime_registration_commit_id=body.runtime_registration_commit_id,
            runtime_registry_id=body.runtime_registry_id,
            actor=actor, idempotency_key=body.idempotency_key,
        )
    except DeploymentReadinessError as exc:
        audit.record(
            event_type="DEPLOYMENT_READINESS_PACKAGE_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(status_code=_deployment_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})

    audit.record(
        event_type="DEPLOYMENT_READINESS_PACKAGE_COMPLETED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={
            "deployment_readiness_package_id": result["deployment_readiness_package_id"],
            "readiness_status": result["readiness_status"],
            "blocking_reason_codes": result["blocking_reason_codes"],
        },
    )
    session.commit()
    return result


@router.get("/{strategy_id}/deployment-readiness-packages")
def list_deployment_readiness_packages_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = list_deployment_readiness_packages(session, strategy_id)
    audit.record(
        event_type="DEPLOYMENT_READINESS_PACKAGE_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "list", "count": len(result)},
    )
    session.commit()
    return {"strategy_id": strategy_id, "packages": result}


@router.get("/{strategy_id}/deployment-readiness-packages/{package_id}")
def get_deployment_readiness_package_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_deployment_readiness_package(session, package_id, strategy_definition_id=strategy_id)
    except DeploymentReadinessError as exc:
        raise HTTPException(status_code=_deployment_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="DEPLOYMENT_READINESS_PACKAGE_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "detail", "deployment_readiness_package_id": package_id},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/deployment-readiness-packages/{package_id}/summary")
def get_deployment_readiness_package_summary_endpoint(
    strategy_id: int, package_id: int,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
):
    try:
        result = get_deployment_readiness_package(session, package_id, strategy_definition_id=strategy_id)
    except DeploymentReadinessError as exc:
        raise HTTPException(status_code=_deployment_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    return {
        "deployment_readiness_package_id": result["deployment_readiness_package_id"],
        "created_readiness_status": result["created_readiness_status"],
        "current_effective_status": result["current_effective_status"],
        "blocking_reason_codes": result["blocking_reason_codes"],
        "warning_reason_codes": result["warning_reason_codes"],
        "missing_requirement_codes": result["missing_requirement_codes"],
        "execution_mode": result["execution_mode"],
    }


@router.get("/{strategy_id}/deployment-readiness-packages/{package_id}/checklist")
def get_deployment_readiness_package_checklist_endpoint(
    strategy_id: int, package_id: int,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
):
    try:
        get_deployment_readiness_package(session, package_id, strategy_definition_id=strategy_id)
        return get_deployment_readiness_package_checklist(session, package_id)
    except DeploymentReadinessError as exc:
        raise HTTPException(status_code=_deployment_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})


@router.get("/{strategy_id}/deployment-readiness-packages/{package_id}/staleness")
def get_deployment_readiness_package_staleness_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        get_deployment_readiness_package(session, package_id, strategy_definition_id=strategy_id)
        result = get_deployment_readiness_package_staleness(session, package_id)
    except DeploymentReadinessError as exc:
        raise HTTPException(status_code=_deployment_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="DEPLOYMENT_READINESS_STALENESS_CHECKED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"deployment_readiness_package_id": package_id, "stale": result["stale"]},
    )
    session.commit()
    return result


@router.post("/{strategy_id}/deployment-readiness-packages/{package_id}/decisions", status_code=status.HTTP_201_CREATED)
def record_deployment_readiness_decision(
    strategy_id: int, package_id: int, body: RecordDeploymentReadinessDecisionBody, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="DEPLOYMENT_READINESS_DECISION_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"deployment_readiness_package_id": package_id, "decision_type": body.decision_type},
    )
    session.commit()
    try:
        result = run_record_deployment_readiness_decision(
            session, strategy_id, package_id,
            decision_type=body.decision_type, reason_code=body.reason_code, reason_text=body.reason_text,
            checklist_confirmations=body.checklist_confirmations, acknowledged_warnings=body.acknowledged_warnings,
            actor=actor, idempotency_key=body.idempotency_key,
        )
    except DeploymentReadinessError as exc:
        audit.record(
            event_type="DEPLOYMENT_READINESS_DECISION_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(status_code=_deployment_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})

    event_by_type = {
        "APPROVE_DEPLOYMENT": "DEPLOYMENT_READINESS_DECISION_APPROVED",
        "REQUEST_DEPLOYMENT_CHANGES": "DEPLOYMENT_READINESS_DECISION_CHANGES_REQUESTED",
        "REJECT_DEPLOYMENT": "DEPLOYMENT_READINESS_DECISION_REJECTED",
    }
    audit.record(
        event_type=event_by_type.get(body.decision_type, "DEPLOYMENT_READINESS_DECISION_APPROVED"), actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"deployment_readiness_decision_id": result["deployment_readiness_decision_id"], "deployment_ready": result["deployment_ready"]},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/deployment-readiness-packages/{package_id}/decision")
def get_deployment_readiness_decision_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    get_deployment_readiness_package(session, package_id, strategy_definition_id=strategy_id)
    result = get_deployment_readiness_decision(session, package_id)
    audit.record(
        event_type="DEPLOYMENT_READINESS_DECISION_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"deployment_readiness_package_id": package_id},
    )
    session.commit()
    return result


@router.post("/{strategy_id}/deployment-readiness-commits", status_code=status.HTTP_201_CREATED)
def create_deployment_readiness_commit(
    strategy_id: int, body: CreateDeploymentReadinessCommitBody, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="DEPLOYMENT_READINESS_COMMIT_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={
            "deployment_readiness_package_id": body.deployment_readiness_package_id,
            "deployment_readiness_decision_id": body.deployment_readiness_decision_id,
        },
    )
    session.commit()
    try:
        result = run_create_deployment_readiness_commit(
            session, strategy_id,
            deployment_readiness_package_id=body.deployment_readiness_package_id,
            deployment_readiness_decision_id=body.deployment_readiness_decision_id,
            runtime_registration_commit_id=body.runtime_registration_commit_id,
            runtime_scope_hash=body.runtime_scope_hash,
            deployment_input_hash=body.deployment_input_hash, decision_input_hash=body.decision_input_hash,
            commit_reason=body.commit_reason, confirmation_text=body.confirmation_text,
            acknowledge_same_actor_warning=body.acknowledge_same_actor_warning,
            actor=actor, idempotency_key=body.idempotency_key,
        )
    except DeploymentReadinessError as exc:
        audit.record(
            event_type="DEPLOYMENT_READINESS_COMMIT_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(status_code=_deployment_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})

    # § STEP12-19 — 완료 Audit("DEPLOYMENT_READY_TO_START")는 여기서 별도로
    # 기록하지 않는다. `run_create_deployment_readiness_commit()` 내부에서
    # Commit/StrategyDeployment/SchedulerPlan/History와 함께 `auto_commit=
    # False`로 add+flush한 뒤, 이 함수가 최상위에서 정확히 한 번 commit할
    # 때 원자적으로 반영된다(§ STEP12-19 Carry-forward 3.1).
    return result


@router.get("/{strategy_id}/deployment-readiness-commits")
def list_deployment_readiness_commits_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = list_deployment_readiness_commits(session, strategy_id)
    audit.record(
        event_type="DEPLOYMENT_READINESS_COMMIT_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "list", "count": len(result)},
    )
    session.commit()
    return {"strategy_id": strategy_id, "commits": result}


@router.get("/{strategy_id}/deployment-readiness-commits/{commit_id}")
def get_deployment_readiness_commit_endpoint(
    strategy_id: int, commit_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_deployment_readiness_commit(session, commit_id, strategy_definition_id=strategy_id)
    except DeploymentReadinessError as exc:
        raise HTTPException(status_code=_deployment_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="DEPLOYMENT_READINESS_COMMIT_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "detail", "deployment_readiness_commit_id": commit_id},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/deployment-readiness-commits/{commit_id}/provenance")
def get_deployment_readiness_commit_provenance_endpoint(
    strategy_id: int, commit_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_deployment_readiness_commit_provenance(session, commit_id, strategy_definition_id=strategy_id)
    except DeploymentReadinessError as exc:
        raise HTTPException(status_code=_deployment_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="DEPLOYMENT_READINESS_PROVENANCE_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"deployment_readiness_commit_id": commit_id},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/deployment-readiness-status")
def get_deployment_readiness_status_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = get_deployment_readiness_status(session, strategy_id)
    audit.record(
        event_type="DEPLOYMENT_READINESS_STATUS_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"deployed": result["deployed"]},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/deployment-readiness-history")
def get_deployment_readiness_history_endpoint(
    strategy_id: int, http_request: Request, runtime_scope_hash: str | None = None,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = get_deployment_readiness_history(session, strategy_id, runtime_scope_hash=runtime_scope_hash)
    audit.record(
        event_type="DEPLOYMENT_READINESS_HISTORY_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"count": len(result), "runtime_scope_hash": runtime_scope_hash},
    )
    session.commit()
    return {"strategy_id": strategy_id, "history": result}


@router.get("/{strategy_id}/deployment-readiness-scopes")
def get_deployment_readiness_scopes_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = get_deployment_readiness_scopes(session, strategy_id)
    audit.record(
        event_type="DEPLOYMENT_READINESS_SCOPES_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "scopes", "count": len(result)},
    )
    session.commit()
    return {"strategy_id": strategy_id, "scopes": result}


@router.get("/{strategy_id}/scheduler-plans")
def list_scheduler_plans_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = list_scheduler_plans(session, strategy_id)
    audit.record(
        event_type="SCHEDULER_PLAN_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "list", "count": len(result)},
    )
    session.commit()
    return {"strategy_id": strategy_id, "scheduler_plans": result}


@router.get("/{strategy_id}/scheduler-plans/{plan_id}")
def get_scheduler_plan_endpoint(
    strategy_id: int, plan_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_scheduler_plan(session, plan_id)
    except DeploymentReadinessError as exc:
        raise HTTPException(status_code=_deployment_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="SCHEDULER_PLAN_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "detail", "scheduler_plan_id": plan_id},
    )
    session.commit()
    return result


# ---------------------------------------------------------------------------
# STEP 12-20 — Operation Readiness Certification
# ---------------------------------------------------------------------------


class CreateOperationReadinessPackageBody(BaseModel):
    deployment_readiness_commit_id: int
    idempotency_key: str | None = Field(default=None, max_length=64)


class RecordOperationReadinessDecisionBody(BaseModel):
    decision_type: str
    reason_code: str
    reason_text: str = Field(min_length=1, max_length=2000)
    checklist_confirmations: dict[str, bool] = Field(default_factory=dict)
    acknowledged_warnings: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=64)


class CreateOperationReadinessCommitBody(BaseModel):
    operation_readiness_package_id: int
    operation_readiness_decision_id: int
    deployment_readiness_commit_id: int
    runtime_scope_hash: str
    operation_input_hash: str
    decision_input_hash: str
    commit_reason: str = Field(min_length=1, max_length=2000)
    confirmation_text: str
    acknowledge_same_actor_warning: bool = False
    idempotency_key: str | None = Field(default=None, max_length=64)


_OPERATION_READINESS_ERROR_STATUS: dict[str, int] = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "PACKAGE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "DECISION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "DEPLOYMENT_READINESS_COMMIT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "RUNTIME_REGISTRATION_COMMIT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "RUNTIME_REGISTRY_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "RUNTIME_SCOPE_MISMATCH": status.HTTP_409_CONFLICT,
    "OWNERSHIP_MISMATCH": status.HTTP_409_CONFLICT,
    "STRATEGY_NOT_ACTIVATED": status.HTTP_409_CONFLICT,
    "DEPLOYMENT_NOT_READY": status.HTTP_409_CONFLICT,
    "OPERATION_ALREADY_CERTIFIED": status.HTTP_409_CONFLICT,
    "OPERATION_NOT_READY": status.HTTP_409_CONFLICT,
    "INVALID_DECISION_TYPE": status.HTTP_400_BAD_REQUEST,
    "INVALID_REASON_CODE": status.HTTP_400_BAD_REQUEST,
    "REASON_TEXT_REQUIRED": status.HTTP_400_BAD_REQUEST,
    "DUPLICATE_OPERATION_READINESS_REVIEW": status.HTTP_409_CONFLICT,
    "DUPLICATE_OPERATION_READINESS_DECISION": status.HTTP_409_CONFLICT,
    "DUPLICATE_OPERATION_READINESS_COMMIT": status.HTTP_409_CONFLICT,
    "DUPLICATE_OPERATION_READINESS_HISTORY": status.HTTP_409_CONFLICT,
    "STALE_OPERATION_READINESS_PACKAGE": status.HTTP_409_CONFLICT,
    "PACKAGE_NOT_READY": status.HTTP_409_CONFLICT,
    "INCOMPLETE_CHECKLIST": status.HTTP_409_CONFLICT,
    "WARNING_NOT_ACKNOWLEDGED": status.HTTP_409_CONFLICT,
    "DECISION_TYPE_MISMATCH": status.HTTP_409_CONFLICT,
    "READINESS_HASH_MISMATCH": status.HTTP_409_CONFLICT,
    "SAME_ACTOR_WARNING_NOT_ACKNOWLEDGED": status.HTTP_409_CONFLICT,
    "IDEMPOTENCY_CONFLICT": status.HTTP_409_CONFLICT,
    "COMMIT_REASON_REQUIRED": status.HTTP_400_BAD_REQUEST,
    "INVALID_CONFIRMATION": status.HTTP_400_BAD_REQUEST,
}


def _operation_readiness_error_status(code: str) -> int:
    return _OPERATION_READINESS_ERROR_STATUS.get(code, status.HTTP_400_BAD_REQUEST)


@router.post("/{strategy_id}/operation-readiness-packages", status_code=status.HTTP_201_CREATED)
def create_operation_readiness_package(
    strategy_id: int, body: CreateOperationReadinessPackageBody, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="OPERATION_READINESS_PACKAGE_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"deployment_readiness_commit_id": body.deployment_readiness_commit_id},
    )
    session.commit()
    try:
        result = run_create_operation_readiness_package(
            session, strategy_id, deployment_readiness_commit_id=body.deployment_readiness_commit_id,
            actor=actor, idempotency_key=body.idempotency_key,
        )
    except OperationReadinessError as exc:
        audit.record(
            event_type="OPERATION_READINESS_PACKAGE_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(status_code=_operation_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})

    audit.record(
        event_type="OPERATION_READINESS_PACKAGE_COMPLETED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={
            "operation_readiness_package_id": result["operation_readiness_package_id"],
            "readiness_status": result["readiness_status"],
            "blocking_reason_codes": result["blocking_reason_codes"],
        },
    )
    session.commit()
    return result


@router.get("/{strategy_id}/operation-readiness-packages")
def list_operation_readiness_packages_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = list_operation_readiness_packages(session, strategy_id)
    audit.record(
        event_type="OPERATION_READINESS_PACKAGE_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "list", "count": len(result)},
    )
    session.commit()
    return {"strategy_id": strategy_id, "packages": result}


@router.get("/{strategy_id}/operation-readiness-packages/{package_id}")
def get_operation_readiness_package_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_operation_readiness_package(session, package_id, strategy_definition_id=strategy_id)
    except OperationReadinessError as exc:
        raise HTTPException(status_code=_operation_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="OPERATION_READINESS_PACKAGE_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "detail", "operation_readiness_package_id": package_id},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/operation-readiness-packages/{package_id}/summary")
def get_operation_readiness_package_summary_endpoint(
    strategy_id: int, package_id: int,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
):
    try:
        result = get_operation_readiness_package(session, package_id, strategy_definition_id=strategy_id)
    except OperationReadinessError as exc:
        raise HTTPException(status_code=_operation_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    return {
        "operation_readiness_package_id": result["operation_readiness_package_id"],
        "created_readiness_status": result["created_readiness_status"],
        "current_effective_status": result["current_effective_status"],
        "blocking_reason_codes": result["blocking_reason_codes"],
        "warning_reason_codes": result["warning_reason_codes"],
        "missing_requirement_codes": result["missing_requirement_codes"],
        "execution_mode": result["execution_mode"],
    }


@router.get("/{strategy_id}/operation-readiness-packages/{package_id}/checklist")
def get_operation_readiness_package_checklist_endpoint(
    strategy_id: int, package_id: int,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
):
    try:
        get_operation_readiness_package(session, package_id, strategy_definition_id=strategy_id)
        return get_operation_readiness_package_checklist(session, package_id)
    except OperationReadinessError as exc:
        raise HTTPException(status_code=_operation_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})


@router.get("/{strategy_id}/operation-readiness-packages/{package_id}/staleness")
def get_operation_readiness_package_staleness_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        get_operation_readiness_package(session, package_id, strategy_definition_id=strategy_id)
        result = get_operation_readiness_package_staleness(session, package_id)
    except OperationReadinessError as exc:
        raise HTTPException(status_code=_operation_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="OPERATION_READINESS_STALENESS_CHECKED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"operation_readiness_package_id": package_id, "stale": result["stale"]},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/operation-readiness-packages/{package_id}/certification")
def get_operation_readiness_certification_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        get_operation_readiness_package(session, package_id, strategy_definition_id=strategy_id)
        result = get_operation_readiness_certification(session, package_id)
    except OperationReadinessError as exc:
        raise HTTPException(status_code=_operation_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="OPERATION_READINESS_CERTIFICATION_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"operation_readiness_package_id": package_id, "all_areas_passed": result["all_areas_passed"]},
    )
    session.commit()
    return result


@router.post("/{strategy_id}/operation-readiness-packages/{package_id}/decisions", status_code=status.HTTP_201_CREATED)
def record_operation_readiness_decision(
    strategy_id: int, package_id: int, body: RecordOperationReadinessDecisionBody, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="OPERATION_READINESS_DECISION_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"operation_readiness_package_id": package_id, "decision_type": body.decision_type},
    )
    session.commit()
    try:
        result = run_record_operation_readiness_decision(
            session, strategy_id, package_id,
            decision_type=body.decision_type, reason_code=body.reason_code, reason_text=body.reason_text,
            checklist_confirmations=body.checklist_confirmations, acknowledged_warnings=body.acknowledged_warnings,
            actor=actor, idempotency_key=body.idempotency_key,
        )
    except OperationReadinessError as exc:
        audit.record(
            event_type="OPERATION_READINESS_DECISION_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(status_code=_operation_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})

    event_by_type = {
        "APPROVE_OPERATION": "OPERATION_READINESS_DECISION_APPROVED",
        "REQUEST_OPERATION_CHANGES": "OPERATION_READINESS_DECISION_CHANGES_REQUESTED",
        "REJECT_OPERATION": "OPERATION_READINESS_DECISION_REJECTED",
    }
    audit.record(
        event_type=event_by_type.get(body.decision_type, "OPERATION_READINESS_DECISION_APPROVED"), actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"operation_readiness_decision_id": result["operation_readiness_decision_id"], "operation_ready": result["operation_ready"]},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/operation-readiness-packages/{package_id}/decision")
def get_operation_readiness_decision_endpoint(
    strategy_id: int, package_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    get_operation_readiness_package(session, package_id, strategy_definition_id=strategy_id)
    result = get_operation_readiness_decision(session, package_id)
    audit.record(
        event_type="OPERATION_READINESS_DECISION_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"operation_readiness_package_id": package_id},
    )
    session.commit()
    return result


@router.post("/{strategy_id}/operation-readiness-commits", status_code=status.HTTP_201_CREATED)
def create_operation_readiness_commit(
    strategy_id: int, body: CreateOperationReadinessCommitBody, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="OPERATION_READINESS_COMMIT_STARTED", actor=actor,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={
            "operation_readiness_package_id": body.operation_readiness_package_id,
            "operation_readiness_decision_id": body.operation_readiness_decision_id,
        },
    )
    session.commit()
    try:
        result = run_create_operation_readiness_commit(
            session, strategy_id,
            operation_readiness_package_id=body.operation_readiness_package_id,
            operation_readiness_decision_id=body.operation_readiness_decision_id,
            deployment_readiness_commit_id=body.deployment_readiness_commit_id,
            runtime_scope_hash=body.runtime_scope_hash,
            operation_input_hash=body.operation_input_hash, decision_input_hash=body.decision_input_hash,
            commit_reason=body.commit_reason, confirmation_text=body.confirmation_text,
            acknowledge_same_actor_warning=body.acknowledge_same_actor_warning,
            actor=actor, idempotency_key=body.idempotency_key,
        )
    except OperationReadinessError as exc:
        audit.record(
            event_type="OPERATION_READINESS_COMMIT_FAILED", actor=actor,
            request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(status_code=_operation_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})

    # § STEP12-20 — 완료 Audit("READY_TO_OPERATE")는 여기서 별도로 기록하지
    # 않는다. `run_create_operation_readiness_commit()` 내부에서 Deployment
    # status_code 전진/Commit/History와 함께 `auto_commit=False`로
    # add+flush한 뒤, 이 함수가 최상위에서 정확히 한 번 commit할 때
    # 원자적으로 반영된다(§ STEP12-19 Carry-forward 3.1과 동일 원칙).
    return result


@router.get("/{strategy_id}/operation-readiness-commits")
def list_operation_readiness_commits_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = list_operation_readiness_commits(session, strategy_id)
    audit.record(
        event_type="OPERATION_READINESS_COMMIT_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "list", "count": len(result)},
    )
    session.commit()
    return {"strategy_id": strategy_id, "commits": result}


@router.get("/{strategy_id}/operation-readiness-commits/{commit_id}")
def get_operation_readiness_commit_endpoint(
    strategy_id: int, commit_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_operation_readiness_commit(session, commit_id, strategy_definition_id=strategy_id)
    except OperationReadinessError as exc:
        raise HTTPException(status_code=_operation_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="OPERATION_READINESS_COMMIT_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"view": "detail", "operation_readiness_commit_id": commit_id},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/operation-readiness-commits/{commit_id}/provenance")
def get_operation_readiness_commit_provenance_endpoint(
    strategy_id: int, commit_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_operation_readiness_commit_provenance(session, commit_id, strategy_definition_id=strategy_id)
    except OperationReadinessError as exc:
        raise HTTPException(status_code=_operation_readiness_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    audit.record(
        event_type="OPERATION_READINESS_PROVENANCE_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"operation_readiness_commit_id": commit_id},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/operation-readiness-status")
def get_operation_readiness_status_endpoint(
    strategy_id: int, http_request: Request,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = get_operation_readiness_status(session, strategy_id)
    audit.record(
        event_type="OPERATION_READINESS_STATUS_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"certified": result["certified"]},
    )
    session.commit()
    return result


@router.get("/{strategy_id}/operation-readiness-history")
def get_operation_readiness_history_endpoint(
    strategy_id: int, http_request: Request, runtime_scope_hash: str | None = None,
    user: AuthenticatedUser = Depends(require_admin), session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    result = get_operation_readiness_history(session, strategy_id, runtime_scope_hash=runtime_scope_hash)
    audit.record(
        event_type="OPERATION_READINESS_HISTORY_VIEWED", actor=user.username,
        request_id=getattr(http_request.state, "request_id", None), strategy_id=str(strategy_id),
        detail={"count": len(result), "runtime_scope_hash": runtime_scope_hash},
    )
    session.commit()
    return {"strategy_id": strategy_id, "history": result}
