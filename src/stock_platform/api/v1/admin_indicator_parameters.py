"""Admin 기술지표 파라미터 CRUD API."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import AuditLogService, get_audit_service, require_admin
from stock_platform.database.session import get_db_session
from stock_platform.indicators.parameter_service import (
    IndicatorEngineParams,
    IndicatorParameterService,
    IndicatorParameterValidationError,
)


def _engine_params_payload(params: IndicatorEngineParams) -> dict[str, Any]:
    # slots=True dataclass 는 __dict__ 가 없음 — asdict 사용
    return asdict(params)


router = APIRouter(
    prefix="/api/v1/admin/indicator-parameters",
    tags=["Admin Indicator Parameters"],
    dependencies=[Depends(require_admin)],
)


class ParameterBody(BaseModel):
    indicator_code: str = Field(min_length=2, max_length=40)
    market_type: str = "STOCK"
    exchange_code: str | None = None
    timeframe: str = "1D"
    parameter_payload: dict[str, Any]
    activate: bool = True


class ParameterUpdateBody(BaseModel):
    parameter_payload: dict[str, Any] | None = None
    is_active: bool | None = None


def _row_dict(row) -> dict[str, Any]:
    return {
        "indicator_parameter_config_id": int(row.indicator_parameter_config_id),
        "indicator_code": row.indicator_code,
        "market_type": row.market_type,
        "exchange_code": row.exchange_code,
        "timeframe": row.timeframe,
        "parameter_payload": row.parameter_payload,
        "version": int(row.version),
        "is_active": bool(row.is_active),
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
def list_parameters(
    indicator_code: str | None = None,
    active_only: bool = False,
    session: Session = Depends(get_db_session),
):
    svc = IndicatorParameterService(session)
    rows = svc.list_configs(
        indicator_code=indicator_code, active_only=active_only
    )
    return {
        "items": [_row_dict(r) for r in rows],
        "system_defaults": svc.defaults(),
        "resolved_engine_params": {
            "STOCK": _engine_params_payload(
                svc.resolve_engine_params(market_type="STOCK")
            ),
            "CRYPTO": _engine_params_payload(
                svc.resolve_engine_params(market_type="CRYPTO")
            ),
        },
    }


@router.get("/meta/defaults")
def get_defaults(session: Session = Depends(get_db_session)):
    return IndicatorParameterService(session).defaults()


@router.post("/preview")
def preview_parameter(body: ParameterBody, session: Session = Depends(get_db_session)):
    svc = IndicatorParameterService(session)
    try:
        return svc.preview(body.indicator_code, body.parameter_payload)
    except IndicatorParameterValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class RestoreDefaultsBody(BaseModel):
    indicator_code: str | None = None
    market_type: str | None = None
    timeframe: str | None = None


@router.post("/restore-defaults")
def restore_defaults(
    body: RestoreDefaultsBody,
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """활성 DB 파라미터를 끄고 시스템 기본값으로 복귀 (행은 유지)."""

    svc = IndicatorParameterService(session)
    deactivated = svc.restore_system_defaults(
        indicator_code=body.indicator_code,
        market_type=body.market_type,
        timeframe=body.timeframe,
    )
    session.commit()
    audit.record(
        event_type="INDICATOR_PARAMETER_RESTORE_DEFAULTS",
        actor="admin",
        detail={
            "deactivated": deactivated,
            "indicator_code": body.indicator_code,
            "market_type": body.market_type,
            "timeframe": body.timeframe,
            "system_defaults": svc.defaults(),
        },
    )
    return {
        "deactivated": deactivated,
        "system_defaults": svc.defaults(),
        "resolved_engine_params": _engine_params_payload(
            svc.resolve_engine_params()
        ),
    }


@router.get("/{config_id}")
def get_parameter(config_id: int, session: Session = Depends(get_db_session)):
    row = IndicatorParameterService(session).get(config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return _row_dict(row)


@router.post("")
def create_parameter(
    body: ParameterBody,
    http_request: Request,
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    svc = IndicatorParameterService(session)
    try:
        row = svc.create(
            indicator_code=body.indicator_code,
            parameter_payload=body.parameter_payload,
            market_type=body.market_type,
            exchange_code=body.exchange_code,
            timeframe=body.timeframe,
            activate=body.activate,
            created_by="admin",
        )
        session.commit()
    except IndicatorParameterValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit.record(
        event_type="INDICATOR_PARAMETER_CREATE",
        actor="admin",
        detail=_row_dict(row),
    )
    return _row_dict(row)


@router.put("/{config_id}")
def update_parameter(
    config_id: int,
    body: ParameterUpdateBody,
    http_request: Request,
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    svc = IndicatorParameterService(session)
    try:
        row = svc.update(
            config_id,
            parameter_payload=body.parameter_payload,
            is_active=body.is_active,
            actor="admin",
        )
        session.commit()
    except LookupError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IndicatorParameterValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit.record(
        event_type="INDICATOR_PARAMETER_UPDATE",
        actor="admin",
        detail=_row_dict(row),
    )
    return _row_dict(row)


@router.post("/{config_id}/activate")
def activate_parameter(
    config_id: int,
    http_request: Request,
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    return update_parameter(
        config_id,
        ParameterUpdateBody(is_active=True),
        http_request,
        session,
        audit,
    )


@router.post("/{config_id}/deactivate")
def deactivate_parameter(
    config_id: int,
    http_request: Request,
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    return update_parameter(
        config_id,
        ParameterUpdateBody(is_active=False),
        http_request,
        session,
        audit,
    )
