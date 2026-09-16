"""STEP 8-9C — LIVE 준비 상태 조회 (조회 전용, ARM/LIVE ON 없음)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_db_session
from stock_platform.risk_engine.kill_switch_models import KillSwitchStatus
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.upbit_live_ops_constants import (
    upbit_live_recommended_risk_payload,
)


router = APIRouter(
    prefix="/api/v1/admin/live-ops",
    tags=["Admin Live Ops Readiness"],
    dependencies=[Depends(require_admin)],
)


@router.get("/readiness")
def admin_live_ops_readiness(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """거래 Scheduler / Tracking / Post-fill / Mock 상태 조회만."""

    settings = get_settings()
    kill = KillSwitchService(session).get_state()
    upbit_count = int(
        session.scalar(
            select(func.count())
            .select_from(UserBrokerAccount)
            .where(func.upper(UserBrokerAccount.broker_code) == "UPBIT")
        )
        or 0
    )
    live_on_count = int(
        session.scalar(
            select(func.count())
            .select_from(UserBrokerAccount)
            .where(
                func.upper(UserBrokerAccount.broker_code) == "UPBIT",
                UserBrokerAccount.live_order_enabled.is_(True),
            )
        )
        or 0
    )
    armed_count = int(
        session.scalar(
            select(func.count())
            .select_from(UserBrokerAccount)
            .where(
                func.upper(UserBrokerAccount.broker_code) == "UPBIT",
                UserBrokerAccount.live_armed.is_(True),
            )
        )
        or 0
    )

    trading_running = None
    sched_snap: dict = {}
    try:
        from stock_platform.trading.upbit_scheduler_readiness import (
            collect_scheduler_readiness,
        )

        snap = collect_scheduler_readiness(settings)
        sched_snap = snap.to_dict()
        trading_running = snap.trading_running
    except Exception:  # noqa: BLE001
        trading_running = None

    track_enabled = bool(
        getattr(settings, "upbit_live_track_enabled", True)
    )
    post_fill_enabled = bool(
        getattr(settings, "post_fill_verify_enabled", True)
    )
    if sched_snap:
        track_enabled = bool(
            sched_snap.get("tracking_scheduler_running", track_enabled)
        )
        post_fill_enabled = bool(
            sched_snap.get(
                "post_fill_scheduler_running", post_fill_enabled
            )
        )
    use_mock = bool(settings.upbit_use_mock)

    actual_state = str(
        sched_snap.get("trading_scheduler_actual_state") or ""
    ).upper()
    desired_state = str(
        sched_snap.get("trading_scheduler_desired_state") or ""
    ).upper()
    source = str(sched_snap.get("source") or "")

    # Scheduler 상태 분류 — RUN/RUNNING 은 정상 운영 (BLOCKED 아님)
    failure_states = {
        "DOWN",
        "CRASH",
        "ERROR",
        "FAILED",
        "FAILURE",
        "JOB_FAILURE",
        "UNHEALTHY",
    }
    running_states = {"RUNNING", "RUN", "READY"}
    paused_states = {"PAUSED", "PAUSE", "STOPPED", "IDLE"}

    if trading_running is True or actual_state in running_states:
        trading_status = "RUNNING"
        trading_ok = True
    elif actual_state in failure_states:
        trading_status = actual_state
        trading_ok = False
    elif trading_running is False or actual_state in paused_states:
        trading_status = "PAUSED"
        trading_ok = True
    elif trading_running is None and source in {
        "unavailable",
        "unknown",
        "",
    }:
        # 프로세스/상태 조회 실패 → DOWN 취급 (BLOCKED)
        trading_status = "DOWN"
        trading_ok = False
    else:
        trading_status = actual_state or "UNKNOWN"
        trading_ok = False

    # Dry-run 준비 게이트 (실주문 게이트와 분리)
    blockers: list[str] = []
    warnings: list[str] = []
    if upbit_count <= 0:
        blockers.append("UPBIT_UBA_MISSING")
    if use_mock:
        blockers.append("UPBIT_USE_MOCK_TRUE")
    # Scheduler RUN/RUNNING/PAUSED 는 BLOCKED 아님
    if trading_status in failure_states or trading_status == "DOWN":
        if trading_status == "DOWN":
            blockers.append("TRADING_SCHEDULER_DOWN")
        elif trading_status in {"CRASH"}:
            blockers.append("TRADING_SCHEDULER_CRASH")
        elif trading_status in {"ERROR", "UNHEALTHY"}:
            blockers.append("TRADING_SCHEDULER_ERROR")
        elif trading_status in {"FAILED", "FAILURE", "JOB_FAILURE"}:
            blockers.append("TRADING_SCHEDULER_JOB_FAILURE")
        else:
            blockers.append("TRADING_SCHEDULER_ERROR")
    elif trading_status == "UNKNOWN":
        warnings.append("TRADING_SCHEDULER_STATUS_UNKNOWN")
    if not track_enabled:
        blockers.append("TRACKING_SCHEDULER_DISABLED")
    if not post_fill_enabled:
        blockers.append("POST_FILL_SCHEDULER_DISABLED")
    if live_on_count > 0:
        warnings.append(f"LIVE_ON_COUNT={live_on_count}")
    if armed_count > 0:
        warnings.append(f"ARMED_COUNT={armed_count}")
    if kill.status == KillSwitchStatus.ACTIVE:
        blockers.append("KILL_SWITCH_ACTIVE")

    dry_run_ready = len(blockers) == 0
    # LIVE 실행 준비: Scheduler RUN 은 정상 운영 상태이므로 허용
    live_execution_ready = (
        dry_run_ready
        and live_on_count > 0
        and armed_count > 0
        and trading_ok
        and trading_status in {"RUNNING", "READY", "PAUSED"}
    )

    pipeline: dict = {}
    try:
        from stock_platform.trading.upbit_live_pipeline_readiness import (
            UpbitLivePipelineReadinessService,
        )

        pipeline = UpbitLivePipelineReadinessService(session).evaluate()
    except Exception as exc:  # noqa: BLE001
        pipeline = {"error": type(exc).__name__}

    return {
        "dry_run_ready": dry_run_ready,
        "live_execution_ready": live_execution_ready,
        "execute_live_allowed_here": False,
        "blockers": blockers,
        "warnings": warnings,
        "uba": {
            "upbit_count": upbit_count,
            "live_on_count": live_on_count,
            "armed_count": armed_count,
        },
        "kill_switch": str(kill.status),
        "upbit_use_mock": use_mock,
        "upbit_live_order_enabled_setting": bool(
            settings.upbit_live_order_enabled
        ),
        "global_live_order_enabled": bool(
            getattr(settings, "global_live_order_enabled", False)
        ),
        "pipeline": pipeline,
        "schedulers": {
            "trading": {
                "desired": desired_state or "PAUSE",
                "running": trading_running,
                "actual": actual_state or sched_snap.get(
                    "trading_scheduler_actual_state"
                ),
                "status": trading_status,
                "paused": sched_snap.get("trading_scheduler_paused"),
                "ok": trading_ok,
                "source": sched_snap.get("source"),
                "control": {
                    "status": "GET /api/v1/realtime-sessions/status",
                    "stop": "POST /api/v1/realtime-sessions/stop-scheduler",
                    "start": "POST /api/v1/realtime-sessions/start-scheduler",
                },
            },
            "tracking": {
                "desired": "RUNNING",
                "enabled": track_enabled,
                "running": track_enabled,
                "ok": track_enabled,
            },
            "post_fill": {
                "desired": "RUNNING",
                "enabled": post_fill_enabled,
                "running": post_fill_enabled,
                "ok": post_fill_enabled,
            },
            "snapshot": sched_snap,
        },
        "recommended_risk": {
            k: str(v) for k, v in upbit_live_recommended_risk_payload().items()
        },
        "notes": [
            "이 API는 조회 전용이다.",
            "ARM / LIVE ON / create_order / cancel_order 를 수행하지 않는다.",
            "dry_run_ready 와 live_execution_ready 를 분리한다.",
            "Trading Scheduler RUN/RUNNING 은 정상 운영 상태이며 BLOCKED 가 아니다.",
            "Scheduler BLOCKED 는 DOWN/CRASH/ERROR/Job Failure 에만 적용한다.",
            "pipeline 은 Shadow/Dry-run·Fill·Recovery 훅 준비 상태다.",
        ],
    }
