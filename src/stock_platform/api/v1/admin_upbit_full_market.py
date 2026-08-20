"""Admin UPBIT Full-Market Dynamic LIVE 제어.

REAL 주문/FULL_MARKET 자동 Enable 없음. 확인 문구 필수.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.operation.upbit_full_market.constants import (
    AI_GATE_ENFORCE,
    CONFIRM_DISABLE_FULL_MARKET,
    CONFIRM_ENABLE_FULL_MARKET,
)
from stock_platform.operation.upbit_full_market.service import (
    UpbitFullMarketAssignmentService,
)


router = APIRouter(
    prefix="/api/v1/admin/autotrading",
    tags=["Admin UPBIT Full Market"],
    dependencies=[Depends(require_admin)],
)


class FullMarketEnableBody(BaseModel):
    confirmation_text: str = Field(..., min_length=3)
    strategy_id: int | None = Field(default=None, ge=1)
    deployment_id: int | None = Field(default=None, ge=1)
    template_symbol: str | None = Field(default=None, max_length=40)
    ai_live_gate_mode: str = Field(default=AI_GATE_ENFORCE, max_length=20)


class FullMarketDisableBody(BaseModel):
    confirmation_text: str = Field(..., min_length=3)


class FullMarketDrySelectBody(BaseModel):
    """실주문 없이 최신 scanner 후보로 선택만 dry-run."""

    candidates: list[dict] | None = None
    scanner_run_id: str | None = None


@router.get("/uba/{user_broker_account_id}/full-market")
def admin_full_market_status(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    svc = UpbitFullMarketAssignmentService(session)
    row = svc.get_or_create(int(user_broker_account_id))
    session.commit()
    return {
        "ok": True,
        **svc.status_dict(int(user_broker_account_id)),
        "confirm_enable": CONFIRM_ENABLE_FULL_MARKET,
        "confirm_disable": CONFIRM_DISABLE_FULL_MARKET,
        "assignment_id": int(row.assignment_id),
    }


@router.post("/uba/{user_broker_account_id}/full-market/enable")
def admin_full_market_enable(
    user_broker_account_id: int,
    body: FullMarketEnableBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
):
    svc = UpbitFullMarketAssignmentService(session)
    result = svc.enable_full_market(
        int(user_broker_account_id),
        confirmation_text=body.confirmation_text,
        actor=str(getattr(admin, "username", None) or admin.user_id),
        strategy_id=body.strategy_id,
        deployment_id=body.deployment_id,
        template_symbol=body.template_symbol,
        ai_live_gate_mode=body.ai_live_gate_mode,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result,
        )
    session.commit()
    return result


@router.post("/uba/{user_broker_account_id}/full-market/disable")
def admin_full_market_disable(
    user_broker_account_id: int,
    body: FullMarketDisableBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
):
    svc = UpbitFullMarketAssignmentService(session)
    result = svc.disable_full_market(
        int(user_broker_account_id),
        confirmation_text=body.confirmation_text,
        actor=str(getattr(admin, "username", None) or admin.user_id),
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result,
        )
    session.commit()
    return result


@router.post("/uba/{user_broker_account_id}/full-market/dry-select")
def admin_full_market_dry_select(
    user_broker_account_id: int,
    body: FullMarketDrySelectBody,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """Broker CREATE 금지 — 선택 정책만 검증."""

    from stock_platform.operation.upbit_opportunity_scanner.scheduler import (
        upbit_opportunity_scanner_scheduler,
    )

    candidates = list(body.candidates or [])
    run_id = body.scanner_run_id
    if not candidates:
        status_sc = upbit_opportunity_scanner_scheduler.status()
        last = status_sc.get("last_result_summary") or {}
        candidates = list(last.get("candidates") or [])
        run_id = run_id or last.get("scanner_run_id") or "dry-select"
        # status summary는 축약본 — dry는 rank/rec 정도만 있어도 OK
    if not run_id:
        run_id = "dry-select"
    svc = UpbitFullMarketAssignmentService(session)
    # dry는 FIXED여도 정책 검증 가능하도록 임시 모드 검사 우회:
    # consume은 mode 체크 → dry_run 전용 경로에서 정책만 돌림
    from stock_platform.operation.upbit_full_market.selection_policy import (
        select_best_eligible_candidate,
    )
    from stock_platform.operation.upbit_full_market.service import (
        load_selection_policy_from_settings,
    )

    assignment = svc.get_or_create(int(user_broker_account_id))
    policy = load_selection_policy_from_settings(assignment=assignment)
    decision = select_best_eligible_candidate(
        candidates,
        policy,
        scanner_run_id=str(run_id),
    )
    session.rollback()  # dry — 아무 것도 persist 하지 않음
    return {
        "ok": decision.selected is not None,
        "dry_run": True,
        "orders_created": 0,
        "scanner_run_id": run_id,
        "reason": decision.reason,
        "skip_trace": decision.skip_trace,
        "selected": (
            {
                "symbol": decision.selected.symbol,
                "rank": decision.selected.rank,
                "score": decision.selected.score,
                "recommendation": decision.selected.recommendation,
                "confidence": decision.selected.confidence,
            }
            if decision.selected
            else None
        ),
        "mode": assignment.mode,
    }
