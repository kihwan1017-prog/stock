"""Admin UPBIT Autotrading readiness / 24x7 Runtime·Worker 제어.

Canonical START/STOP: POST .../uba/{id}/start|stop (AutotradingOrchestrator).
개별 Runtime/Worker/Exit API는 backward compatible 유지.
Activation/LIVE/ARM 자동 토글은 Orchestrator에서도 금지(재승인 경로 제외).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.trading.autotrading_master_gate import (
    admin_set_uba_strategy_link_active,
    evaluate_uba_autotrading_ready,
)


router = APIRouter(
    prefix="/api/v1/admin/autotrading",
    tags=["Admin Autotrading Readiness"],
    dependencies=[Depends(require_admin)],
)


class StrategyLinkActiveBody(BaseModel):
    strategy_id: int = Field(..., ge=1)
    is_active: bool = True


class Upbit24x7RuntimeBody(BaseModel):
    strategy_id: int = Field(..., ge=1)
    confirmation_text: str = Field(..., min_length=3)


class Upbit24x7ConfirmBody(BaseModel):
    confirmation_text: str = Field(..., min_length=3)


@router.get("/uba/{user_broker_account_id}/readiness")
def admin_uba_autotrading_readiness(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """UBA 자동매매 Master Gate — 상태 조회만 (시작/주문 없음)."""

    return evaluate_uba_autotrading_ready(
        session, user_broker_account_id=int(user_broker_account_id)
    )


class KiwoomMarketRealtimeStartBody(BaseModel):
    """KIWOOM 시세 WS 명시 START — 주문/LIVE/ARM 변경 없음."""

    user_broker_account_id: int = Field(..., ge=1)
    symbols: list[str] = Field(..., min_length=1)
    confirmation_text: str = Field(..., min_length=8)
    require_real: bool = True


class KiwoomMarketRealtimeStopBody(BaseModel):
    confirmation_text: str = Field(..., min_length=8)


@router.get("/kiwoom/market-realtime/status")
def admin_kiwoom_market_realtime_status(
    _: AuthenticatedUser = Depends(require_admin),
):
    """KIWOOM 시세 WS 상태 READ. START/주문 없음. 토큰 미포함."""

    from stock_platform.realtime.kiwoom_market_realtime_runtime import (
        kiwoom_market_realtime_runtime,
    )

    return {
        **kiwoom_market_realtime_runtime.status(),
        "mutate_allowed": False,
    }


@router.post("/kiwoom/market-realtime/start")
async def admin_kiwoom_market_realtime_start(
    body: KiwoomMarketRealtimeStartBody,
    _: AuthenticatedUser = Depends(require_admin),
):
    """KIWOOM REAL 시세 WS START. Upbit runner/UBA 상태 변경 없음."""

    confirm = str(body.confirmation_text or "").strip().upper()
    if "START KIWOOM MARKET REALTIME" not in confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "CONFIRMATION_REQUIRED",
                "message": "confirmation_text must include "
                "'START KIWOOM MARKET REALTIME'",
            },
        )
    from stock_platform.realtime.kiwoom_market_realtime_runtime import (
        kiwoom_market_realtime_runtime,
    )

    result = await kiwoom_market_realtime_runtime.start(
        user_broker_account_id=int(body.user_broker_account_id),
        symbols=list(body.symbols),
        require_real=bool(body.require_real),
    )
    if not result.get("started"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": str(result.get("reason") or "START_BLOCKED"),
                "message": "kiwoom market realtime start blocked",
                "result": result,
            },
        )
    return result


@router.post("/kiwoom/market-realtime/stop")
async def admin_kiwoom_market_realtime_stop(
    body: KiwoomMarketRealtimeStopBody,
    _: AuthenticatedUser = Depends(require_admin),
):
    """KIWOOM 시세 WS STOP. Upbit 시세/runner 유지."""

    confirm = str(body.confirmation_text or "").strip().upper()
    if "STOP KIWOOM MARKET REALTIME" not in confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "CONFIRMATION_REQUIRED",
                "message": "confirmation_text must include "
                "'STOP KIWOOM MARKET REALTIME'",
            },
        )
    from stock_platform.realtime.kiwoom_market_realtime_runtime import (
        kiwoom_market_realtime_runtime,
    )

    return await kiwoom_market_realtime_runtime.stop()


@router.get("/uba/{user_broker_account_id}/kiwoom-market-registration")
def admin_kiwoom_market_registration(
    user_broker_account_id: int,
    strategy_id: int = Query(default=17579),
    symbol: str = Query(default="034310"),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """시세 consumer 등록 dry-readiness. Runtime START 없음."""

    from stock_platform.realtime.kiwoom_market_runtime_readiness import (
        evaluate_kiwoom_market_runtime_registration,
    )

    return evaluate_kiwoom_market_runtime_registration(
        session,
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=int(strategy_id),
        symbol=str(symbol),
    )


@router.get("/exit-monitor/status")
def admin_exit_monitor_status(
    _: AuthenticatedUser = Depends(require_admin),
):
    """Exit Monitor 상태. in-memory READ만. START/STOP 없음."""

    from stock_platform.trading.upbit_24x7_control import exit_monitor_status

    return {
        **exit_monitor_status(),
        "mutate_allowed": False,
    }


@router.get("/uba/{user_broker_account_id}/strategy-runtime/status")
def admin_uba_strategy_runtime_status(
    user_broker_account_id: int,
    strategy_id: int | None = Query(default=None),
    _: AuthenticatedUser = Depends(require_admin),
):
    """Strategy Runtime 상태. in-memory READ만. START/STOP 없음."""

    from stock_platform.trading.upbit_24x7_control import runtime_status_for_uba

    return runtime_status_for_uba(
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=strategy_id,
    )


@router.get("/live-outbox-worker/status")
def admin_live_outbox_worker_status(
    _: AuthenticatedUser = Depends(require_admin),
):
    """LIVE Outbox Worker 상태. ENABLE은 env/settings — 이 API는 조회만."""

    from stock_platform.order.live_outbox_worker_runtime import (
        live_outbox_worker_runtime,
    )

    status_payload = live_outbox_worker_runtime.status()
    return {
        **status_payload,
        "enable_via": "LIVE_OUTBOX_WORKER_ENABLED settings/env",
        "note": (
            "ENABLE alone does not bypass LIVE/ARM/Activation; "
            "dispatch still Fail Closed"
        ),
        "mutate_allowed": False,
    }


@router.get("/uba/{user_broker_account_id}/24x7-control")
def admin_uba_24x7_control_status(
    user_broker_account_id: int,
    strategy_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """UPBIT 24/7 Runtime/Worker/Exit 상태. START ALL 없음."""

    from stock_platform.trading.upbit_24x7_control import (
        combined_control_status,
    )

    return combined_control_status(
        session,
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=strategy_id,
    )


@router.get("/uba/{user_broker_account_id}/ops-status")
def admin_uba_ops_status(
    user_broker_account_id: int,
    strategy_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """UBA 운영 상태 SoT aggregate (AUTO TRADING / TTL / Unattended)."""

    from stock_platform.trading.uba_operational_summary import (
        build_uba_operational_summary,
    )

    out = build_uba_operational_summary(
        session,
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=strategy_id,
    )
    # FIXED_SYMBOL assignment ensure (get_or_create) persist
    try:
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
    return out


# NOTE: full-market FIXED row ensure는 summary 내부 get_or_create.
# 세션 autocommit 없음 → 위에서 commit.


class UnattendedEnableBody(BaseModel):
    """Unattended lease ACK — LIVE approval_phrase 미사용."""

    confirmation_text: str = Field(..., min_length=8)
    reason: str = Field(..., min_length=3, max_length=2000)
    horizon_hours: int | None = Field(default=None, ge=1, le=168)
    correlation_id: str | None = Field(default=None, max_length=128)
    source: str = Field(default="ADMIN_UI", min_length=3, max_length=32)


class UnattendedDisableBody(BaseModel):
    confirmation_text: str = Field(..., min_length=8)
    reason: str = Field(..., min_length=3, max_length=2000)


@router.get("/uba/{user_broker_account_id}/unattended")
def admin_uba_unattended_status(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    from stock_platform.trading.live_unattended_authorization_service import (
        LiveUnattendedAuthorizationService,
    )

    return LiveUnattendedAuthorizationService(session).status_dict(
        int(user_broker_account_id)
    )


@router.post("/uba/{user_broker_account_id}/unattended/enable")
def admin_uba_unattended_enable(
    user_broker_account_id: int,
    body: UnattendedEnableBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    """24H Unattended 명시 승인. 자동 ON 금지."""

    from stock_platform.trading.live_unattended_authorization_service import (
        LiveUnattendedAuthorizationService,
        LiveUnattendedError,
    )

    try:
        return LiveUnattendedAuthorizationService(session).enable(
            int(user_broker_account_id),
            actor=user.username,
            confirmation_text=body.confirmation_text,
            reason=body.reason,
            source=body.source,
            horizon_hours=body.horizon_hours,
            correlation_id=body.correlation_id,
        )
    except LiveUnattendedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/uba/{user_broker_account_id}/unattended/reauthorize")
def admin_uba_unattended_reauthorize(
    user_broker_account_id: int,
    body: UnattendedEnableBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    """만료/PROTECTIVE 이후 24H 재승인 + canonical LIVE/ARM/stack 복구."""

    from stock_platform.trading.live_unattended_authorization_service import (
        LiveUnattendedAuthorizationService,
        LiveUnattendedError,
    )

    try:
        return LiveUnattendedAuthorizationService(session).reauthorize(
            int(user_broker_account_id),
            actor=user.username,
            confirmation_text=body.confirmation_text,
            reason=body.reason,
            source=body.source,
            horizon_hours=body.horizon_hours,
            correlation_id=body.correlation_id,
        )
    except LiveUnattendedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/uba/{user_broker_account_id}/unattended/disable")
def admin_uba_unattended_disable(
    user_broker_account_id: int,
    body: UnattendedDisableBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    from stock_platform.trading.live_unattended_authorization_service import (
        LiveUnattendedAuthorizationService,
        LiveUnattendedError,
    )

    try:
        return LiveUnattendedAuthorizationService(session).disable(
            int(user_broker_account_id),
            actor=user.username,
            confirmation_text=body.confirmation_text,
            reason=body.reason,
            fail_closed=True,
        )
    except LiveUnattendedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


class UnattendedAutoRenewBody(BaseModel):
    enabled: bool


@router.post("/uba/{user_broker_account_id}/unattended/auto-renew")
def admin_uba_unattended_auto_renew_toggle(
    user_broker_account_id: int,
    body: UnattendedAutoRenewBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    """24H lease 자동 갱신 opt-in/out — ACTIVE lease 필수."""

    from stock_platform.trading.live_unattended_authorization_service import (
        LiveUnattendedAuthorizationService,
        LiveUnattendedError,
    )

    try:
        return LiveUnattendedAuthorizationService(session).set_auto_renew_enabled(
            int(user_broker_account_id),
            enabled=bool(body.enabled),
            actor=user.username,
        )
    except LiveUnattendedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.get("/uba/{user_broker_account_id}/unattended/horizon-auto-renew/preview")
def admin_uba_unattended_horizon_auto_renew_preview(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """READ-ONLY dry evaluation — would_renew / projected expiry."""

    from stock_platform.trading.live_unattended_authorization_service import (
        LiveUnattendedAuthorizationService,
    )

    return LiveUnattendedAuthorizationService(
        session
    ).dry_horizon_auto_renew_evaluation(int(user_broker_account_id))


@router.post("/uba/{user_broker_account_id}/strategy-runtime/start")
async def admin_uba_strategy_runtime_start(
    user_broker_account_id: int,
    body: Upbit24x7RuntimeBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    from stock_platform.trading.upbit_24x7_control import (
        Upbit24x7ControlError,
        start_upbit_strategy_runtime,
    )

    try:
        return await start_upbit_strategy_runtime(
            session,
            user_broker_account_id=int(user_broker_account_id),
            strategy_id=int(body.strategy_id),
            actor=user.username,
            confirmation_text=body.confirmation_text,
        )
    except Upbit24x7ControlError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/uba/{user_broker_account_id}/strategy-runtime/stop")
async def admin_uba_strategy_runtime_stop(
    user_broker_account_id: int,
    body: Upbit24x7RuntimeBody,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    from stock_platform.trading.upbit_24x7_control import (
        Upbit24x7ControlError,
        stop_upbit_strategy_runtime,
    )

    try:
        return await stop_upbit_strategy_runtime(
            session,
            user_broker_account_id=int(user_broker_account_id),
            strategy_id=int(body.strategy_id),
            confirmation_text=body.confirmation_text,
        )
    except Upbit24x7ControlError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/live-outbox-worker/start")
async def admin_live_outbox_worker_start(
    body: Upbit24x7ConfirmBody,
    _: AuthenticatedUser = Depends(require_admin),
):
    """operator START. asyncio.create_task 가 필요하므로 async 핸들러로 둔다."""

    from stock_platform.trading.upbit_24x7_control import (
        Upbit24x7ControlError,
        start_live_outbox_worker,
    )

    try:
        return start_live_outbox_worker(
            confirmation_text=body.confirmation_text,
        )
    except Upbit24x7ControlError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/live-outbox-worker/stop")
async def admin_live_outbox_worker_stop(
    body: Upbit24x7ConfirmBody,
    _: AuthenticatedUser = Depends(require_admin),
):
    """operator STOP. running loop 에서 shutdown task 를 스케줄한다."""

    from stock_platform.trading.upbit_24x7_control import (
        Upbit24x7ControlError,
        stop_live_outbox_worker,
    )

    try:
        return stop_live_outbox_worker(
            confirmation_text=body.confirmation_text,
        )
    except Upbit24x7ControlError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/exit-monitor/start")
async def admin_exit_monitor_start(
    body: Upbit24x7ConfirmBody,
    _: AuthenticatedUser = Depends(require_admin),
):
    """operator START. live_upbit 플래그는 변경하지 않는다."""

    from stock_platform.trading.upbit_24x7_control import (
        Upbit24x7ControlError,
        start_exit_monitor,
    )

    try:
        return start_exit_monitor(
            confirmation_text=body.confirmation_text,
        )
    except Upbit24x7ControlError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/exit-monitor/stop")
async def admin_exit_monitor_stop(
    body: Upbit24x7ConfirmBody,
    _: AuthenticatedUser = Depends(require_admin),
):
    """operator STOP. live scan scheduler 를 내린다. START는 이 STEP에서 호출 금지."""

    from stock_platform.trading.upbit_24x7_control import (
        Upbit24x7ControlError,
        stop_exit_monitor,
    )

    try:
        return await stop_exit_monitor(
            confirmation_text=body.confirmation_text,
        )
    except Upbit24x7ControlError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/uba/{user_broker_account_id}/strategy-link")
def admin_uba_strategy_link_set_active(
    user_broker_account_id: int,
    body: StrategyLinkActiveBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    """승인된 Strategy link 활성/비활성. Runtime RUN·주문 전송 없음."""

    try:
        result = admin_set_uba_strategy_link_active(
            session,
            user_broker_account_id=int(user_broker_account_id),
            strategy_id=int(body.strategy_id),
            is_active=bool(body.is_active),
            actor=user.username,
        )
        session.commit()
        return result
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


class OrchestratorStartBody(BaseModel):
    """Canonical autotrading START — REAL 주문 강제 생성 없음."""

    reauthorize_unattended: bool = False
    strategy_id: int | None = Field(default=None, ge=1)
    correlation_id: str | None = Field(default=None, max_length=120)


class OrchestratorStopBody(BaseModel):
    """ENTRY_ONLY(기본)=신규진입 중지·보호유지 / FULL=스택 종료(OPEN 있으면 차단)."""

    mode: str = Field(default="ENTRY_ONLY", max_length=32)
    strategy_id: int | None = Field(default=None, ge=1)


@router.get("/uba/{user_broker_account_id}/status")
async def admin_uba_orchestrator_status(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """Orchestrator status SoT (readiness + ops)."""

    from stock_platform.trading.autotrading_orchestrator import (
        AutotradingOrchestrator,
    )

    return await AutotradingOrchestrator(session).status(
        int(user_broker_account_id)
    )


@router.post("/uba/{user_broker_account_id}/start")
async def admin_uba_orchestrator_start(
    user_broker_account_id: int,
    body: OrchestratorStartBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    """Canonical START — UBA single-flight · fail-closed · idempotent."""

    from stock_platform.trading.autotrading_orchestrator import (
        AutotradingOrchestrator,
    )

    return await AutotradingOrchestrator(session).start(
        int(user_broker_account_id),
        actor=user.username,
        reauthorize_unattended=bool(body.reauthorize_unattended),
        strategy_id=body.strategy_id,
        correlation_id=body.correlation_id,
    )


@router.post("/uba/{user_broker_account_id}/stop")
async def admin_uba_orchestrator_stop(
    user_broker_account_id: int,
    body: OrchestratorStopBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    """Canonical STOP — default ENTRY_ONLY (Exit/LIVE/ARM 유지)."""

    from stock_platform.trading.autotrading_orchestrator import (
        AutotradingOrchestrator,
    )

    return await AutotradingOrchestrator(session).stop(
        int(user_broker_account_id),
        actor=user.username,
        mode=str(body.mode or "ENTRY_ONLY"),
        strategy_id=body.strategy_id,
    )