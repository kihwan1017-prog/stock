"""UBA 운영 상태 SoT aggregate — Admin UI용.

FE에서 RUNNING을 추정하지 않도록 서버가 auto_trading_state를 계산한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.broker.live_transition_service import (
    LiveTradingTransitionService,
)
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_session_expiry import (
    activation_remaining_seconds,
    aware_utc,
)
from stock_platform.trading.live_unattended_authorization_service import (
    LiveUnattendedAuthorizationService,
)
from stock_platform.trading.upbit_24x7_control import combined_control_status


def _remaining_label(seconds: int) -> str:
    if seconds <= 0:
        return "EXPIRED"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def build_uba_operational_summary(
    session: Session,
    *,
    user_broker_account_id: int,
    strategy_id: int | None = None,
) -> dict[str, Any]:
    uba_id = int(user_broker_account_id)
    uba = session.get(UserBrokerAccount, uba_id)
    ctrl = combined_control_status(
        session,
        user_broker_account_id=uba_id,
        strategy_id=strategy_id,
    )
    unattended = LiveUnattendedAuthorizationService(session).status_dict(
        uba_id
    )

    now = datetime.now(timezone.utc)
    arm_on = False
    arm_remaining = 0
    arm_expires_at = None
    if uba is not None:
        arm_exp = aware_utc(getattr(uba, "arm_expires_at", None))
        arm_on = bool(uba.live_armed) and (
            arm_exp is None or arm_exp > now
        )
        if arm_exp is not None:
            arm_expires_at = arm_exp.isoformat()
            arm_remaining = max(0, int((arm_exp - now).total_seconds()))

    act = None
    activation_expires_at = None
    activation_remaining = 0
    if uba is not None:
        act = LiveTradingTransitionService(session).peek_active(
            broker_code=str(uba.broker_code or "").upper(),
            user_broker_account_id=uba_id,
        )
        if act is not None:
            activation_remaining = activation_remaining_seconds(act, now=now)
            exp = aware_utc(act.expires_at)
            activation_expires_at = exp.isoformat() if exp else None

    live_on = bool(getattr(uba, "live_order_enabled", False)) if uba else False
    rt = str(ctrl.get("strategy_runtime") or "STOPPED").upper()
    rn = "RUNNING" if rt == "RUNNING" else rt
    wk = str(ctrl.get("outbox_worker") or "STOPPED").upper()
    ex = str(ctrl.get("exit_monitor") or "STOPPED").upper()
    stack = [rt == "RUNNING", wk == "RUNNING", ex == "RUNNING"]
    # Runner ≈ strategy runtime for UPBIT 24x7
    runner_running = rt == "RUNNING"
    stack_running = sum(
        1 for x in (rt == "RUNNING", runner_running, wk == "RUNNING", ex == "RUNNING")
        if x
    )

    blockers: list[str] = []
    warnings: list[str] = []
    try:
        from stock_platform.risk_engine.kill_switch_service import (
            KillSwitchService,
        )

        if KillSwitchService(session).is_active():
            blockers.append("KILL_SWITCH_ACTIVE")
    except Exception:  # noqa: BLE001
        pass

    if not live_on:
        blockers.append("LIVE_OFF")
    if not arm_on:
        blockers.append("ARM_OFF")
    if str(ctrl.get("activation") or "") != "ACTIVE":
        blockers.append("ACTIVATION_INACTIVE")
    if arm_on and 0 < arm_remaining <= 600:
        warnings.append("ARM_EXPIRING_SOON")
    if 0 < activation_remaining <= 600:
        warnings.append("ACTIVATION_EXPIRING_SOON")
    if unattended.get("unattended_enabled") and int(
        unattended.get("remaining_seconds") or 0
    ) <= 3600:
        warnings.append("UNATTENDED_EXPIRING_SOON")

    # AI vs AUTO 분리 — AI HOLD는 AUTO STOP이 아님
    ai_state = "UNKNOWN"
    try:
        from stock_platform.trading.autotrading_master_gate import (
            evaluate_uba_autotrading_ready,
        )

        ready = evaluate_uba_autotrading_ready(
            session, user_broker_account_id=uba_id
        )
        for b in ready.get("blockers") or []:
            code = str(b)
            if code and code not in blockers:
                if code.startswith("AI_"):
                    continue
                blockers.append(code)
        ai_checks = (ready.get("checks") or {}).get("ai_gate") or {}
        ai_state = str(
            ai_checks.get("assumed_result")
            or ai_checks.get("recommendation")
            or "HOLD"
        ).upper()
    except Exception:  # noqa: BLE001
        ai_state = "UNKNOWN"

    market_feed = {
        "status": "UNKNOWN",
        "source": str(getattr(uba, "broker_code", "") or "").upper() or None,
    }
    try:
        from stock_platform.trading.autotrading_master_gate import (
            evaluate_uba_autotrading_ready,
        )

        ready = evaluate_uba_autotrading_ready(
            session, user_broker_account_id=uba_id
        )
        feed = (ready.get("checks") or {}).get("market_feed") or {}
        stale = feed.get("stale")
        healthy = feed.get("healthy")
        if healthy is True and stale is not True:
            market_feed = {
                "status": "REAL_FRESH",
                "source": market_feed["source"],
                "detail": feed,
            }
        elif stale is True:
            market_feed = {
                "status": "REAL_STALE",
                "source": market_feed["source"],
                "detail": feed,
            }
        elif feed.get("connected") is False:
            market_feed = {
                "status": "DISCONNECTED",
                "source": market_feed["source"],
                "detail": feed,
            }
        else:
            market_feed = {
                "status": "UNKNOWN",
                "source": market_feed["source"],
                "detail": feed,
            }
    except Exception:  # noqa: BLE001
        pass

    # SoT auto_trading_state
    if "KILL_SWITCH_ACTIVE" in blockers:
        auto_state = "BLOCKED"
    elif not live_on or not arm_on or str(ctrl.get("activation")) != "ACTIVE":
        auto_state = "STOPPED"
    elif rt == "RUNNING" and wk == "RUNNING":
        if blockers:
            auto_state = "DEGRADED"
        else:
            auto_state = "RUNNING"
    elif rt in {"STOPPED", "PAUSED"} and live_on and arm_on:
        auto_state = "WAITING_SIGNAL"
    else:
        auto_state = "DEGRADED" if blockers else "STOPPED"

    primary_blocker = blockers[0] if blockers else None

    return {
        "user_broker_account_id": uba_id,
        "broker_code": (
            str(uba.broker_code).upper() if uba is not None else None
        ),
        "auto_trading_state": auto_state,
        "live": "ON" if live_on else "OFF",
        "arm": "ON" if arm_on else "OFF",
        "arm_expires_at": arm_expires_at,
        "arm_remaining_seconds": arm_remaining,
        "arm_remaining_label": _remaining_label(arm_remaining) if arm_on else "OFF",
        "activation": str(ctrl.get("activation") or "INACTIVE"),
        "activation_id": (
            int(act.live_trading_transition_id) if act is not None else None
        ),
        "activation_expires_at": activation_expires_at,
        "activation_remaining_seconds": activation_remaining,
        "activation_remaining_label": _remaining_label(activation_remaining),
        "unattended": unattended,
        "runtime": rt,
        "runner": "RUNNING" if runner_running else "STOPPED",
        "outbox_worker": wk,
        "exit_monitor": ex,
        "runtime_stack": {
            "running_count": stack_running,
            "total": 4,
            "label": f"{stack_running}/4 RUNNING",
            "runtime": rt,
            "runner": "RUNNING" if runner_running else "STOPPED",
            "outbox_worker": wk,
            "exit_monitor": ex,
        },
        "market_feed": market_feed,
        "ai_state": ai_state,
        "blockers": blockers,
        "warnings": warnings,
        "primary_blocker": primary_blocker,
        "control": ctrl,
        "as_of": now.isoformat(),
    }
