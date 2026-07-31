"""STEP 12-13 — Portfolio Validation Admin API.

복수의 승인 Strategy Definition과 기존 Backtest 결과만 조합해 검증
Report를 생성한다. 실제 Portfolio를 생성하거나 자금을 배분하지 않고,
새 Backtest를 실행하지 않는다. URL이 특정 strategy_id에 종속되지
않으므로(다대다 조합) `admin_strategies.py`가 아니라 별도 라우터로
둔다."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.strategy_draft_approval.portfolio_validation import (
    DEFAULT_CONCENTRATION_THRESHOLD,
    DEFAULT_CORRELATION_THRESHOLD,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_MINIMUM_OVERLAP_DAYS,
    PortfolioValidationError,
    get_portfolio_validation_correlations,
    get_portfolio_validation_exposures,
    get_portfolio_validation_report,
    get_portfolio_validation_risk_contributions,
    get_portfolio_validation_summary,
    run_portfolio_validation,
)
from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/portfolio-validations",
    tags=["Admin Portfolio Validation"],
    dependencies=[Depends(require_admin)],
)


class RunPortfolioValidationBody(BaseModel):
    strategy_definition_ids: list[int] = Field(min_length=2, max_length=10)
    backtest_run_ids: list[int] = Field(min_length=2, max_length=10)
    weighting_method: str = Field(default="EQUAL_WEIGHT")
    strategy_weights: dict[int, Decimal] | None = None
    alignment_policy: str = Field(default="INTERSECTION")
    minimum_overlap_days: int = Field(default=DEFAULT_MINIMUM_OVERLAP_DAYS, ge=1)
    initial_capital: Decimal = Field(default=DEFAULT_INITIAL_CAPITAL, gt=0)
    correlation_threshold: Decimal = Field(default=DEFAULT_CORRELATION_THRESHOLD, ge=-1, le=1)
    concentration_threshold: Decimal = Field(default=DEFAULT_CONCENTRATION_THRESHOLD, ge=0, le=1)
    idempotency_key: str | None = Field(default=None, max_length=64)


_PORTFOLIO_VALIDATION_ERROR_STATUS = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "BACKTEST_RUN_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "OWNERSHIP_MISMATCH": status.HTTP_409_CONFLICT,
    "PROVENANCE_MISMATCH": status.HTTP_409_CONFLICT,
    "DEFINITION_NOT_READY": status.HTTP_409_CONFLICT,
    "SPECIFICATION_NOT_COMPILABLE": status.HTTP_409_CONFLICT,
    "BACKTEST_NOT_COMPLETED": status.HTTP_409_CONFLICT,
    "EXECUTABLE_HASH_MISSING": status.HTTP_409_CONFLICT,
    "RUNTIME_INPUT_HASH_MISSING": status.HTTP_409_CONFLICT,
    "EQUITY_CURVE_MISSING": status.HTTP_409_CONFLICT,
    "TOO_FEW_STRATEGIES": status.HTTP_400_BAD_REQUEST,
    "TOO_MANY_STRATEGIES": status.HTTP_400_BAD_REQUEST,
    "DUPLICATE_STRATEGY": status.HTTP_400_BAD_REQUEST,
    "DUPLICATE_BACKTEST_RUN": status.HTTP_400_BAD_REQUEST,
    "INVALID_REQUEST": status.HTTP_400_BAD_REQUEST,
    "UNSUPPORTED_WEIGHTING_METHOD": status.HTTP_400_BAD_REQUEST,
    "MISSING_WEIGHT": status.HTTP_400_BAD_REQUEST,
    "INVALID_WEIGHT": status.HTTP_400_BAD_REQUEST,
    "INVALID_WEIGHT_SUM": status.HTTP_400_BAD_REQUEST,
    "UNSUPPORTED_ALIGNMENT_POLICY": status.HTTP_400_BAD_REQUEST,
    "DUPLICATE_DATE": status.HTTP_400_BAD_REQUEST,
    "INVALID_EQUITY_VALUE": status.HTTP_400_BAD_REQUEST,
    "INSUFFICIENT_OVERLAP": status.HTTP_400_BAD_REQUEST,
    "IDEMPOTENCY_CONFLICT": status.HTTP_409_CONFLICT,
}


def _error_status(code: str) -> int:
    return _PORTFOLIO_VALIDATION_ERROR_STATUS.get(code, status.HTTP_400_BAD_REQUEST)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_portfolio_validation(
    body: RunPortfolioValidationBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = user.username
    audit.record(
        event_type="PORTFOLIO_VALIDATION_STARTED",
        actor=actor,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "strategy_definition_ids": body.strategy_definition_ids,
            "backtest_run_ids": body.backtest_run_ids,
            "weighting_method": body.weighting_method,
        },
    )
    session.commit()
    try:
        result = run_portfolio_validation(
            session,
            strategy_definition_ids=body.strategy_definition_ids,
            backtest_run_ids=body.backtest_run_ids,
            weighting_method=body.weighting_method,
            strategy_weights=body.strategy_weights,
            alignment_policy=body.alignment_policy,
            minimum_overlap_days=body.minimum_overlap_days,
            initial_capital=body.initial_capital,
            correlation_threshold=body.correlation_threshold,
            concentration_threshold=body.concentration_threshold,
            actor=actor,
            idempotency_key=body.idempotency_key,
        )
    except PortfolioValidationError as exc:
        audit.record(
            event_type="PORTFOLIO_VALIDATION_FAILED",
            actor=actor,
            request_id=getattr(http_request.state, "request_id", None),
            detail={"code": exc.code, "message": exc.message},
        )
        session.commit()
        raise HTTPException(
            status_code=_error_status(exc.code), detail={"code": exc.code, "message": exc.message}
        )

    audit.record(
        event_type="PORTFOLIO_VALIDATION_COMPLETED",
        actor=actor,
        request_id=getattr(http_request.state, "request_id", None),
        detail={
            "portfolio_validation_report_id": result["portfolio_validation_report_id"],
            "validation_status": result["validation_status"],
            "robustness_score": (
                str(result["robustness_score"]) if result["robustness_score"] is not None else None
            ),
        },
    )
    session.commit()
    return {
        "report_id": result["portfolio_validation_report_id"],
        "validation_status": result["validation_status"],
        "robustness_score": result["robustness_score"],
        "portfolio_summary": {
            "strategy_count": result["strategy_count"],
            "observation_count": result["observation_count"],
            "portfolio_kpi": result["portfolio_kpi_payload"],
        },
        "idempotent_replay": result["idempotent_replay"],
    }


def _record_viewed(audit: AuditLogService, *, actor: str, request_id: Any, report_id: int, view: str) -> None:
    audit.record(
        event_type="PORTFOLIO_VALIDATION_VIEWED", actor=actor, request_id=request_id,
        detail={"portfolio_validation_report_id": report_id, "view": view},
    )


@router.get("/{report_id}")
def get_portfolio_validation(
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_portfolio_validation_report(session, report_id)
    except PortfolioValidationError as exc:
        raise HTTPException(status_code=_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    _record_viewed(
        audit, actor=user.username, request_id=getattr(http_request.state, "request_id", None),
        report_id=report_id, view="detail",
    )
    session.commit()
    return result


@router.get("/{report_id}/summary")
def get_portfolio_validation_summary_endpoint(
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_portfolio_validation_summary(session, report_id)
    except PortfolioValidationError as exc:
        raise HTTPException(status_code=_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    _record_viewed(
        audit, actor=user.username, request_id=getattr(http_request.state, "request_id", None),
        report_id=report_id, view="summary",
    )
    session.commit()
    return result


@router.get("/{report_id}/correlations")
def get_portfolio_validation_correlations_endpoint(
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_portfolio_validation_correlations(session, report_id)
    except PortfolioValidationError as exc:
        raise HTTPException(status_code=_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    _record_viewed(
        audit, actor=user.username, request_id=getattr(http_request.state, "request_id", None),
        report_id=report_id, view="correlations",
    )
    session.commit()
    return result


@router.get("/{report_id}/risk-contributions")
def get_portfolio_validation_risk_contributions_endpoint(
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_portfolio_validation_risk_contributions(session, report_id)
    except PortfolioValidationError as exc:
        raise HTTPException(status_code=_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    _record_viewed(
        audit, actor=user.username, request_id=getattr(http_request.state, "request_id", None),
        report_id=report_id, view="risk_contributions",
    )
    session.commit()
    return result


@router.get("/{report_id}/exposures")
def get_portfolio_validation_exposures_endpoint(
    report_id: int,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        result = get_portfolio_validation_exposures(session, report_id)
    except PortfolioValidationError as exc:
        raise HTTPException(status_code=_error_status(exc.code), detail={"code": exc.code, "message": exc.message})
    _record_viewed(
        audit, actor=user.username, request_id=getattr(http_request.state, "request_id", None),
        report_id=report_id, view="exposures",
    )
    session.commit()
    return result
