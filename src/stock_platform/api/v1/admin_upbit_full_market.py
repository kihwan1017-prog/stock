"""Admin UPBIT Full-Market Dynamic LIVE 제어.

REAL 주문/FULL_MARKET 자동 Enable 없음. 확인 문구 필수.
"""

from __future__ import annotations

from typing import Any

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


# ── Portfolio (FULL_MARKET_PORTFOLIO) ──


class PortfolioEnableBody(BaseModel):
    confirmation_text: str = Field(..., min_length=3)
    strategy_id: int | None = Field(default=None, ge=1)
    deployment_id: int | None = Field(default=None, ge=1)
    template_symbol: str | None = Field(default=None, max_length=40)
    portfolio_capital_limit_krw: float | None = Field(default=None, ge=0)
    max_positions: int = Field(default=3, ge=1, le=10)


class PortfolioDisableBody(BaseModel):
    confirmation_text: str = Field(..., min_length=3)
    fallback_mode: str = Field(default="FULL_MARKET_SINGLE", max_length=40)


class PortfolioPolicyPatchBody(BaseModel):
    max_positions: int | None = Field(default=None, ge=1, le=10)
    portfolio_capital_limit_krw: float | None = Field(default=None, ge=0)
    per_position_target_pct: float | None = Field(default=None, gt=0, le=1)
    max_symbol_exposure_pct: float | None = Field(default=None, gt=0, le=1)
    max_total_exposure_pct: float | None = Field(default=None, gt=0, le=1)
    min_cash_reserve_pct: float | None = Field(default=None, ge=0, le=1)
    daily_loss_limit_pct: float | None = Field(default=None, gt=0, le=1)
    consecutive_loss_limit: int | None = Field(default=None, ge=1, le=50)
    allow_averaging_down: bool | None = None
    allow_duplicate_symbol: bool | None = None
    entry_cooldown_seconds: int | None = Field(default=None, ge=0)
    candidate_max_age_seconds: int | None = Field(default=None, ge=60)
    portfolio_max_pending_entries: int | None = Field(default=None, ge=1, le=10)
    portfolio_daily_entry_limit: int | None = Field(default=None, ge=1, le=100)
    entry_state: str | None = Field(default=None, max_length=30)
    entry_signal_policy: str | None = Field(default=None, max_length=40)
    candidate_hold_seconds: int | None = Field(default=None, ge=0, le=86400)
    candidate_max_wait_seconds: int | None = Field(default=None, ge=60, le=86400)
    candidate_switch_min_score_delta: float | None = Field(
        default=None, ge=0, le=100
    )


class PortfolioPreviewBody(BaseModel):
    symbol: str = Field(default="KRW-ETH", max_length=40)
    scanner_score: float = Field(default=80.0)
    ai_confidence: float = Field(default=0.85)
    volatility: str = Field(default="MEDIUM", max_length=20)
    available_krw: float | None = Field(default=None, ge=0)
    account_max_order_amount: float | None = Field(default=None, ge=0)


class PortfolioDryTopKBody(BaseModel):
    candidates: list[dict] | None = None
    scanner_run_id: str | None = None
    available_krw: float | None = Field(default=500_000, ge=0)
    account_max_order_amount: float | None = Field(default=10_000, ge=0)


@router.get("/uba/{user_broker_account_id}/portfolio")
def admin_portfolio_status(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    from stock_platform.operation.upbit_full_market.constants import (
        CONFIRM_DISABLE_PORTFOLIO,
        CONFIRM_ENABLE_PORTFOLIO,
    )
    from stock_platform.operation.upbit_full_market.portfolio_service import (
        UpbitPortfolioService,
    )

    fm = UpbitFullMarketAssignmentService(session)
    pf = UpbitPortfolioService(session)
    fm.get_or_create(int(user_broker_account_id))
    pf.get_or_create_policy(int(user_broker_account_id))
    session.commit()
    return {
        "ok": True,
        **fm.status_dict(int(user_broker_account_id)),
        "policy": pf.policy_dict(int(user_broker_account_id)),
        "slots": pf.list_slots(int(user_broker_account_id)),
        "summary": pf.drawer_summary(int(user_broker_account_id)),
        "confirm_enable": CONFIRM_ENABLE_PORTFOLIO,
        "confirm_disable": CONFIRM_DISABLE_PORTFOLIO,
        "orders_created": 0,
    }


@router.post("/uba/{user_broker_account_id}/portfolio/enable")
def admin_portfolio_enable(
    user_broker_account_id: int,
    body: PortfolioEnableBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
):
    from stock_platform.operation.upbit_full_market.portfolio_service import (
        UpbitPortfolioService,
    )

    result = UpbitPortfolioService(session).enable_portfolio(
        int(user_broker_account_id),
        confirmation_text=body.confirmation_text,
        actor=str(getattr(admin, "username", None) or admin.user_id),
        strategy_id=body.strategy_id,
        deployment_id=body.deployment_id,
        template_symbol=body.template_symbol,
        portfolio_capital_limit_krw=body.portfolio_capital_limit_krw,
        max_positions=body.max_positions,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result,
        )
    session.commit()
    return result


@router.post("/uba/{user_broker_account_id}/portfolio/disable")
def admin_portfolio_disable(
    user_broker_account_id: int,
    body: PortfolioDisableBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
):
    from stock_platform.operation.upbit_full_market.portfolio_service import (
        UpbitPortfolioService,
    )

    result = UpbitPortfolioService(session).disable_portfolio(
        int(user_broker_account_id),
        confirmation_text=body.confirmation_text,
        actor=str(getattr(admin, "username", None) or admin.user_id),
        fallback_mode=body.fallback_mode,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result,
        )
    session.commit()
    return result


@router.patch("/uba/{user_broker_account_id}/portfolio/policy")
def admin_portfolio_policy_patch(
    user_broker_account_id: int,
    body: PortfolioPolicyPatchBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
):
    from stock_platform.operation.upbit_full_market.portfolio_service import (
        UpbitPortfolioService,
    )

    patches = body.model_dump(exclude_none=True)
    result = UpbitPortfolioService(session).update_policy(
        int(user_broker_account_id),
        patches=patches,
        actor=str(getattr(admin, "username", None) or admin.user_id),
    )
    session.commit()
    return result


@router.post("/uba/{user_broker_account_id}/portfolio/preview-sizing")
def admin_portfolio_preview_sizing(
    user_broker_account_id: int,
    body: PortfolioPreviewBody,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    from stock_platform.operation.upbit_full_market.portfolio_service import (
        UpbitPortfolioService,
    )

    result = UpbitPortfolioService(session).preview_allocation(
        int(user_broker_account_id),
        symbol=body.symbol,
        scanner_score=body.scanner_score,
        ai_confidence=body.ai_confidence,
        volatility=body.volatility,
        available_krw=body.available_krw,
        account_max_order_amount=body.account_max_order_amount,
    )
    session.rollback()
    return {"ok": True, **result}


@router.post("/uba/{user_broker_account_id}/portfolio/dry-topk")
def admin_portfolio_dry_topk(
    user_broker_account_id: int,
    body: PortfolioDryTopKBody,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """실주문 없이 Top-K slot 배정 시뮬레이션."""

    from decimal import Decimal

    from stock_platform.operation.upbit_full_market.constants import (
        MODE_FULL_MARKET_PORTFOLIO,
    )
    from stock_platform.operation.upbit_full_market.portfolio_service import (
        UpbitPortfolioService,
    )

    candidates = list(body.candidates or [])
    run_id = body.scanner_run_id or "dry-topk"
    fm = UpbitFullMarketAssignmentService(session)
    assignment = fm.get_or_create(int(user_broker_account_id))
    # dry: 임시 PORTFOLIO mode로 정책 검증 (persist 후 rollback)
    prev_mode = assignment.mode
    assignment.mode = MODE_FULL_MARKET_PORTFOLIO
    pf = UpbitPortfolioService(session)
    policy = pf.get_or_create_policy(int(user_broker_account_id))
    policy.enabled = True
    pf.ensure_slots(
        int(user_broker_account_id),
        max_positions=int(policy.max_positions),
        strategy_id=assignment.strategy_id,
        deployment_id=assignment.deployment_id,
    )
    result = pf.consume_top_k(
        int(user_broker_account_id),
        candidates=candidates,
        scanner_run_id=str(run_id),
        available_krw=(
            Decimal(str(body.available_krw))
            if body.available_krw is not None
            else None
        ),
        account_max_order_amount=(
            Decimal(str(body.account_max_order_amount))
            if body.account_max_order_amount is not None
            else None
        ),
        dry_run=True,
    )
    assignment.mode = prev_mode
    session.rollback()
    return result


class PortfolioRecoverStaleEntryBody(BaseModel):
    confirmation_text: str = Field(..., min_length=3)
    timeout_seconds: float | None = Field(default=None, ge=60, le=180)
    check_broker_open_orders: bool = True


@router.post(
    "/uba/{user_broker_account_id}/portfolio/recover-stale-entry-pending"
)
def admin_portfolio_recover_stale_entry_pending(
    user_broker_account_id: int,
    body: PortfolioRecoverStaleEntryBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
):
    """ENTRY_PENDING without order 고착 해제. REAL CREATE/CANCEL 없음."""

    from stock_platform.operation.upbit_full_market.constants import (
        CONFIRM_RECOVER_STALE_ENTRY_PENDING,
    )
    from stock_platform.operation.upbit_full_market.portfolio_service import (
        UpbitPortfolioService,
    )

    broker_syms: set[str] | None = None
    if body.check_broker_open_orders:
        try:
            from stock_platform.broker.credential_adapter_factory import (
                build_upbit_settings_from_vault,
            )
            from stock_platform.broker.credential_vault_service import (
                BrokerCredentialVaultService,
            )
            from stock_platform.broker.upbit.order_client import (
                UpbitOrderRestClient,
            )

            resolved = BrokerCredentialVaultService(session).resolve_for_runtime(
                int(user_broker_account_id),
                expected_broker="UPBIT",
                require_verified=True,
                touch_last_used=False,
            )
            client = UpbitOrderRestClient(
                settings=build_upbit_settings_from_vault(resolved),
                user_broker_account_id=int(user_broker_account_id),
            )
            # READ-ONLY — wait/watch only (CREATE/CANCEL 없음)
            remote_rows: list[Any] = []
            remote_rows.extend(client.list_orders(state="wait", limit=100) or [])
            remote_rows.extend(client.list_orders(state="watch", limit=100) or [])
            broker_syms = set()
            for row in remote_rows:
                if not isinstance(row, dict):
                    continue
                market = str(
                    row.get("market") or row.get("symbol") or ""
                ).upper()
                if market:
                    broker_syms.add(market)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "ok": False,
                    "reason": "BROKER_OPEN_ORDER_CHECK_FAILED",
                    "error": type(exc).__name__,
                },
            ) from exc

    result = UpbitPortfolioService(session).recover_stale_entry_pending_without_order(
        int(user_broker_account_id),
        timeout_seconds=body.timeout_seconds,
        confirmation_text=body.confirmation_text,
        broker_open_symbols=broker_syms,
        actor=str(getattr(admin, "username", None) or admin.user_id),
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result,
        )
    session.commit()
class PortfolioAlignPipelineBody(BaseModel):
    confirmation_text: str = Field(..., min_length=3)


@router.post(
    "/uba/{user_broker_account_id}/portfolio/align-entry-pipeline"
)
def admin_portfolio_align_entry_pipeline(
    user_broker_account_id: int,
    body: PortfolioAlignPipelineBody,
    session: Session = Depends(get_db_session),
    admin: AuthenticatedUser = Depends(require_admin),
):
    """구 ENTRY_PENDING+reserve(주문없음) → WAITING_SIGNAL+reserve0 + runtime sync."""

    from stock_platform.operation.upbit_full_market.constants import (
        CONFIRM_ALIGN_PORTFOLIO_ENTRY_PIPELINE,
    )
    from stock_platform.operation.upbit_full_market.portfolio_service import (
        UpbitPortfolioService,
    )

    result = UpbitPortfolioService(session).align_legacy_reserved_entry_pending(
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
    return {
        **result,
        "confirm_phrase": CONFIRM_ALIGN_PORTFOLIO_ENTRY_PIPELINE,
        "orders_created": 0,
    }


@router.get("/uba/{user_broker_account_id}/portfolio/entry-evaluations")
def admin_portfolio_entry_evaluations(
    user_broker_account_id: int,
    _: AuthenticatedUser = Depends(require_admin),
):
    """슬롯별 in-memory entry 평가 요약 (고빈도 DB write 없음)."""

    from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
        portfolio_entry_telemetry,
    )

    return {
        "ok": True,
        "user_broker_account_id": int(user_broker_account_id),
        "evaluations": portfolio_entry_telemetry.snapshot(
            int(user_broker_account_id)
        ),
        "orders_created": 0,
    }
