"""Admin UPBIT Autotrading readiness / 24x7 RuntimeÂ·Worker ì ì´.

Canonical START/STOP: POST .../uba/{id}/start|stop (AutotradingOrchestrator).
ê°ë³ Runtime/Worker/Exit APIë backward compatible ì ì§.
Activation/LIVE/ARM ìë í ê¸ì Orchestratorììë ê¸ì§(ì¬ì¹ì¸ ê²½ë¡ ì ì¸).
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
    """UBA ìëë§¤ë§¤ Master Gate â ìí ì¡°íë§ (ìì/ì£¼ë¬¸ ìì)."""

    return evaluate_uba_autotrading_ready(
        session, user_broker_account_id=int(user_broker_account_id)
    )


class KiwoomMarketRealtimeStartBody(BaseModel):
    """KIWOOM ìì¸ WS ëªì START â ì£¼ë¬¸/LIVE/ARM ë³ê²½ ìì."""

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
    """KIWOOM ìì¸ WS ìí READ. START/ì£¼ë¬¸ ìì. í í° ë¯¸í¬í¨."""

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
    """KIWOOM REAL ìì¸ WS START. Upbit runner/UBA ìí ë³ê²½ ìì."""

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
    """KIWOOM ìì¸ WS STOP. Upbit ìì¸/runner ì ì§."""

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
    """ìì¸ consumer ë±ë¡ dry-readiness. Runtime START ìì."""

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
    """Exit Monitor ìí. in-memory READë§. START/STOP ìì."""

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
    """Strategy Runtime ìí. in-memory READë§. START/STOP ìì."""

    from stock_platform.trading.upbit_24x7_control import runtime_status_for_uba

    return runtime_status_for_uba(
        user_broker_account_id=int(user_broker_account_id),
        strategy_id=strategy_id,
    )


@router.get("/live-outbox-worker/status")
def admin_live_outbox_worker_status(
    _: AuthenticatedUser = Depends(require_admin),
):
    """LIVE Outbox Worker ìí. ENABLEì env/settings â ì´ APIë ì¡°íë§."""

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
    """UPBIT 24/7 Runtime/Worker/Exit ìí. START ALL ìì."""

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
    """UBA ì´ì ìí SoT aggregate (AUTO TRADING / TTL / Unattended)."""

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


# NOTE: full-market FIXED row ensureë summary ë´ë¶ get_or_create.
# ì¸ì autocommit ìì â ììì commit.


class UnattendedEnableBody(BaseModel):
    """Unattended lease ACK â LIVE approval_phrase ë¯¸ì¬ì©."""

    confirmation_text: str = Field(..., min_length=8)
    reason: str = Field(..., min_length=3, max_length=2000)
    horizon_hours: int | None = Field(default=None, ge=1, le=168)
    correlation_id: str | None = Field(default=None, max_length=128)
    source: str = Field(default="ADMIN_UI", min_length=3, max_length=32)
    # HOURS_24 (UPBIT) | MARKET_HOURS (KIWOOM). Noneì´ë©´ brokerë¡ ì¶ë¡ .
    authorization_mode: str | None = Field(default=None, max_length=32)
    # KIWOOM MARKET_HOURS â ìµì¼ ì¥ ìì ìë lifecycle opt-in
    next_trading_day_auto_start: bool = False


class NextDayAutoStartBody(BaseModel):
    """Kiwoom next-trading-day auto-start opt-in/out."""

    enabled: bool
    confirmation_text: str = Field(..., min_length=8)
    reason: str | None = Field(default=None, max_length=2000)


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
    """24H Unattended ëªì ì¹ì¸. ìë ON ê¸ì§."""

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
            authorization_mode=body.authorization_mode,
            next_trading_day_auto_start=bool(
                body.next_trading_day_auto_start
            ),
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
    """ë§ë£/PROTECTIVE ì´í 24H ì¬ì¹ì¸ + canonical LIVE/ARM/stack ë³µêµ¬."""

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
    """24H lease ìë ê°±ì  opt-in/out â ACTIVE lease íì."""

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
    """READ-ONLY dry evaluation â would_renew / projected expiry."""

    from stock_platform.trading.live_unattended_authorization_service import (
        LiveUnattendedAuthorizationService,
    )

    return LiveUnattendedAuthorizationService(
        session
    ).dry_horizon_auto_renew_evaluation(int(user_broker_account_id))


@router.get("/uba/{user_broker_account_id}/kiwoom-lifecycle")
def admin_uba_kiwoom_lifecycle_status(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """Kiwoom next-trading-day lifecycle ìí (READ)."""

    from stock_platform.trading.kiwoom_trading_day_lifecycle import (
        KiwoomTradingDayLifecycleService,
    )

    return KiwoomTradingDayLifecycleService(session).status_dict(
        int(user_broker_account_id)
    )


@router.get("/uba/{user_broker_account_id}/kiwoom-lifecycle/precheck")
def admin_uba_kiwoom_lifecycle_precheck(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """ìë ìì precheck (READ-ONLY, fail-closed)."""

    from stock_platform.trading.kiwoom_trading_day_lifecycle import (
        KiwoomTradingDayLifecycleService,
    )

    return KiwoomTradingDayLifecycleService(session).evaluate_auto_start_precheck(
        int(user_broker_account_id)
    )


@router.get("/uba/{user_broker_account_id}/kiwoom-lifecycle/preview")
def admin_uba_kiwoom_lifecycle_preview(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """ë¤ì ê±°ëì¼ auto-start dry preview â LIVE mutation ìì."""

    from stock_platform.trading.kiwoom_trading_day_lifecycle import (
        KiwoomTradingDayLifecycleService,
    )

    return KiwoomTradingDayLifecycleService(session).preview_next_session(
        int(user_broker_account_id)
    )


@router.post("/uba/{user_broker_account_id}/kiwoom-lifecycle/next-day-auto-start")
def admin_uba_kiwoom_next_day_auto_start(
    user_broker_account_id: int,
    body: NextDayAutoStartBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    """ìµì¼ ì¥ ìì ìë lifecycle opt-in/out (íì¸ ë¬¸êµ¬ íì)."""

    from stock_platform.trading.kiwoom_trading_day_lifecycle import (
        KiwoomTradingDayLifecycleService,
    )
    from stock_platform.trading.live_unattended_authorization_service import (
        LiveUnattendedError,
    )

    try:
        return KiwoomTradingDayLifecycleService(
            session
        ).set_next_trading_day_auto_start(
            int(user_broker_account_id),
            enabled=bool(body.enabled),
            actor=user.username,
            confirmation_text=body.confirmation_text,
            reason=body.reason,
        )
    except LiveUnattendedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/uba/{user_broker_account_id}/kiwoom-lifecycle/tick")
async def admin_uba_kiwoom_lifecycle_tick(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    """공식 lifecycle tick + stack restore (장중 ENSURE_STACK).

    REAL 주문 강제 생성 없음. feed/runtime/runner만 idempotent 복구.
    """

    from stock_platform.trading.kiwoom_trading_day_lifecycle import (
        KiwoomTradingDayLifecycleService,
    )
    from stock_platform.trading.kiwoom_unattended_stack_restore import (
        restore_kiwoom_trading_stack,
    )

    uba_id = int(user_broker_account_id)
    tick = KiwoomTradingDayLifecycleService(session).tick_uba(
        uba_id, actor=f"admin:{user.username}"
    )
    session.commit()
    stack: dict | None = None
    if tick.get("action") in {
        "ENSURE_STACK",
        "RESTART_PIPELINE_SCHEDULED",
    } or tick.get("phase") == "TRADING":
        stack = await restore_kiwoom_trading_stack(
            session,
            user_broker_account_id=uba_id,
            actor=f"admin:{user.username}:TICK",
        )
        session.commit()
    return {
        "tick": tick,
        "stack": stack,
        "REAL_ORDER_MUTATION": 0,
        "actor": user.username,
    }


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
    """operator START. asyncio.create_task ê° íìíë¯ë¡ async í¸ë¤ë¬ë¡ ëë¤."""

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
    """operator STOP. running loop ìì shutdown task ë¥¼ ì¤ì¼ì¤íë¤."""

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
    """operator START. live_upbit íëê·¸ë ë³ê²½íì§ ìëë¤."""

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
    """operator STOP. live scan scheduler ë¥¼ ë´ë¦°ë¤. STARTë ì´ STEPìì í¸ì¶ ê¸ì§."""

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
    """ì¹ì¸ë Strategy link íì±/ë¹íì±. Runtime RUNÂ·ì£¼ë¬¸ ì ì¡ ìì."""

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
    """Canonical autotrading START â REAL ì£¼ë¬¸ ê°ì  ìì± ìì."""

    reauthorize_unattended: bool = False
    strategy_id: int | None = Field(default=None, ge=1)
    correlation_id: str | None = Field(default=None, max_length=120)


class OrchestratorStopBody(BaseModel):
    """ENTRY_ONLY(ê¸°ë³¸)=ì ê·ì§ì ì¤ì§Â·ë³´í¸ì ì§ / FULL=ì¤í ì¢ë£(OPEN ìì¼ë©´ ì°¨ë¨)."""

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
    """Canonical START â UBA single-flight Â· fail-closed Â· idempotent."""

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
    """Canonical STOP â default ENTRY_ONLY (Exit/LIVE/ARM ì ì§)."""

    from stock_platform.trading.autotrading_orchestrator import (
        AutotradingOrchestrator,
    )

    return await AutotradingOrchestrator(session).stop(
        int(user_broker_account_id),
        actor=user.username,
        mode=str(body.mode or "ENTRY_ONLY"),
        strategy_id=body.strategy_id,
    )


@router.get("/uba/{user_broker_account_id}/research/collection-status")
def admin_uba_research_collection_status(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """연구 데이터 수집 현황 — READ ONLY. REAL/LIVE/주문 무관."""

    from stock_platform.operation.upbit_market_context.research_collection_status import (
        build_research_collection_status,
    )

    return build_research_collection_status(
        session,
        user_broker_account_id=int(user_broker_account_id),
    )


@router.get("/uba/{user_broker_account_id}/filled-exit-open-binding")
def admin_uba_filled_exit_open_binding(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """Invariant FILLED_EXIT_WITH_OPEN_BINDING — READ ONLY."""

    from stock_platform.broker.upbit.filled_exit_finalizer import (
        detect_filled_exit_with_open_binding,
        dry_run_ghost_reconciliation,
    )

    detected = detect_filled_exit_with_open_binding(
        session, user_broker_account_id=int(user_broker_account_id)
    )
    dry = dry_run_ghost_reconciliation(
        session, user_broker_account_id=int(user_broker_account_id)
    )
    return {"detected": detected, "dry_run": dry}


@router.post("/uba/{user_broker_account_id}/filled-exit-open-binding/reconcile")
def admin_uba_reconcile_filled_exit_open_binding(
    user_broker_account_id: int,
    dry_run: bool = True,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    """SAFE_TO_CLOSE ghost binding만 canonical finalizer로 정리.

    dry_run=true(기본): 주문/SQL 직접 UPDATE 없음.
    dry_run=false: FILLED SELL 증거 있는 것만 binding close (브로커 주문 없음).
    """

    from stock_platform.broker.upbit.filled_exit_finalizer import (
        reconcile_safe_ghost_bindings,
    )

    result = reconcile_safe_ghost_bindings(
        session,
        user_broker_account_id=int(user_broker_account_id),
        actor=f"ADMIN_RECONCILE:{user.username}",
        dry_run=bool(dry_run),
    )
    if not dry_run:
        session.commit()
    return result


@router.get("/uba/{user_broker_account_id}/kiwoom-funnel")
def admin_uba_kiwoom_funnel(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """KIWOOM funnel + FIRST_ZERO_STAGE — READ ONLY."""

    from stock_platform.trading.kiwoom_funnel_observability import (
        build_kiwoom_funnel_snapshot,
    )

    return build_kiwoom_funnel_snapshot(
        session, user_broker_account_id=int(user_broker_account_id)
    )


@router.get("/uba/{user_broker_account_id}/pipeline-liveness")
def admin_uba_pipeline_liveness(
    user_broker_account_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """Pipeline liveness + FIRST_ZERO + classification — READ ONLY SoT."""

    from stock_platform.trading.pipeline_liveness_service import (
        build_pipeline_liveness_snapshot,
    )

    return build_pipeline_liveness_snapshot(
        session, user_broker_account_id=int(user_broker_account_id)
    )


@router.get("/health")
def admin_autotrading_health_overview(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """UPBIT/KIWOOM canonical autotrading health overview."""

    from stock_platform.trading.autotrading_health_service import (
        build_autotrading_health_overview,
    )
    from stock_platform.trading.autotrading_reliability_watchdog import (
        autotrading_reliability_watchdog,
    )

    out = build_autotrading_health_overview(session)
    out["watchdog"] = autotrading_reliability_watchdog.status()
    return out


@router.get("/uba/{user_broker_account_id}/health")
def admin_uba_autotrading_health(
    user_broker_account_id: int,
    strategy_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """Per-UBA TradingHealthSnapshot — watchdog SoT."""

    from stock_platform.trading.autotrading_health_service import (
        build_trading_health_snapshot,
    )
    from stock_platform.trading.autotrading_reliability_watchdog import (
        autotrading_reliability_watchdog,
        get_stack_forensic,
    )

    uba_id = int(user_broker_account_id)
    snap = build_trading_health_snapshot(
        session, user_broker_account_id=uba_id, strategy_id=strategy_id
    )
    broker = str(snap.get("market") or "UPBIT")
    snap["watchdog"] = autotrading_reliability_watchdog.status()
    snap["stack_forensic"] = get_stack_forensic(market=broker, uba_id=uba_id)
    return snap
