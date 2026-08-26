"""UBA 운영 상태 SoT aggregate — Admin UI용.

FE에서 RUNNING을 추정하지 않도록 서버가 auto_trading_state를 계산한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
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


def _map_market_feed_status(feed: dict[str, Any]) -> str:
    """master_gate market_feed → Admin Feed 라벨.

    gate는 ok/reason을 쓰고 healthy 키는 없을 수 있다.
    """

    healthy = feed.get("healthy")
    if healthy is None:
        healthy = feed.get("ok")
    stale = feed.get("stale")
    if stale is None:
        reason = str(feed.get("reason") or "").upper()
        stale = reason in {"QUOTE_STALE", "NO_RECENT_QUOTE"}
    quote_ws = (
        feed.get("quote_ws") if isinstance(feed.get("quote_ws"), dict) else {}
    )
    connected = feed.get("connected")
    if connected is None and "connected" in quote_ws:
        connected = quote_ws.get("connected")
    if connected is None and "running" in quote_ws:
        connected = quote_ws.get("running")
    if connected is False:
        return "DISCONNECTED"
    if stale is True:
        return "REAL_STALE"
    if healthy is True and stale is not True:
        return "REAL_FRESH"
    if healthy is False:
        return "UNHEALTHY"
    return "UNKNOWN"


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
    # KIWOOM UBA에 UPBIT master gate를 merge하면 ACTIVATION_INACTIVE 등 오탐
    ai_state = "UNKNOWN"
    broker_u = str(getattr(uba, "broker_code", "") or "").upper() if uba else ""
    try:
        if broker_u == "UPBIT":
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
        elif broker_u == "KIWOOM":
            # broker-correct blockers만 (UPBIT gate 오탐 제거)
            for noise in (
                "UBA_BROKER_MISMATCH",
                "UPBIT_CREDENTIAL_UNRESOLVED",
                "STRATEGY_NOT_LIVE_APPROVED",
            ):
                if noise in blockers and str(ctrl.get("activation")) == "ACTIVE":
                    # activation peek가 ACTIVE면 UPBIT 하드코딩 오탐 제거 후보
                    pass
            ai_state = "N/A_KIWOOM"
    except Exception:  # noqa: BLE001
        ai_state = "UNKNOWN"

    market_feed = {
        "status": "UNKNOWN",
        "source": str(getattr(uba, "broker_code", "") or "").upper() or None,
    }
    try:
        if broker_u == "UPBIT":
            from stock_platform.trading.autotrading_master_gate import (
                evaluate_uba_autotrading_ready,
            )

            ready = evaluate_uba_autotrading_ready(
                session, user_broker_account_id=uba_id
            )
            feed = (ready.get("checks") or {}).get("market_feed") or {}
            market_feed = {
                "status": _map_market_feed_status(feed),
                "source": market_feed["source"],
                "detail": feed,
            }
        elif broker_u == "KIWOOM":
            from stock_platform.realtime.kiwoom_market_realtime_runtime import (
                kiwoom_market_realtime_runtime as kmr,
            )

            st = kmr.status()
            running = bool(st.get("running"))
            connected = bool(st.get("connected"))
            if connected and running:
                feed_status = "REAL_FRESH"
            elif running and not connected:
                feed_status = "DISCONNECTED"
            else:
                feed_status = "DISCONNECTED"
            market_feed = {
                "status": feed_status,
                "source": "KIWOOM",
                "detail": {
                    "running": running,
                    "connected": connected,
                    "execution_process_kiwoom_use_mock": st.get(
                        "execution_process_kiwoom_use_mock"
                    ),
                    "process_market_environment": st.get(
                        "process_market_environment"
                    ),
                    "note": (
                        "process kiwoom_use_mock alone does not block REAL feed; "
                        "KIWOOM_MARKET_DATA_USE_MOCK=true does"
                    ),
                },
            }
    except Exception:  # noqa: BLE001
        pass

    # ghost OPEN invariant (UPBIT only) — telemetry
    ghost_invariant: dict[str, Any] | None = None
    if broker_u == "UPBIT":
        try:
            from stock_platform.broker.upbit.filled_exit_finalizer import (
                detect_filled_exit_with_open_binding,
            )

            ghost_invariant = detect_filled_exit_with_open_binding(
                session, user_broker_account_id=uba_id
            )
            if int(ghost_invariant.get("count") or 0) > 0:
                blockers.append("FILLED_EXIT_WITH_OPEN_BINDING")
                warnings.append("GHOST_OPEN_BINDING")
        except Exception:  # noqa: BLE001
            ghost_invariant = None

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

    full_market: dict[str, Any] = {
        "mode": "FIXED_SYMBOL",
        "full_market_enabled": False,
    }
    scanner_summary: dict[str, Any] | None = None
    kiwoom_funnel: dict[str, Any] | None = None
    try:
        if broker_u == "UPBIT":
            from stock_platform.operation.upbit_full_market.service import (
                UpbitFullMarketAssignmentService,
            )
            from stock_platform.operation.upbit_opportunity_scanner.scheduler import (
                upbit_opportunity_scanner_scheduler,
            )

            # 기존 FIXED 보호 — 없으면 FIXED_SYMBOL row 생성
            template = None
            try:
                dep = (ctrl.get("deployment") or {}) if isinstance(ctrl, dict) else {}
                template = dep.get("symbol") or ctrl.get("symbol")
            except Exception:  # noqa: BLE001
                template = None
            if not template and strategy_id is not None:
                try:
                    from stock_platform.strategy_deployment.entities import (
                        StrategyDeploymentEntity,
                    )

                    dep_row = session.scalar(
                        select(StrategyDeploymentEntity)
                        .where(
                            StrategyDeploymentEntity.strategy_id
                            == int(strategy_id),
                            StrategyDeploymentEntity.status_code == "ACTIVE",
                        )
                        .limit(1)
                    )
                    if dep_row is not None and dep_row.symbol:
                        template = str(dep_row.symbol)
                except Exception:  # noqa: BLE001
                    pass
            if not template:
                template = "KRW-XRP" if strategy_id == 17483 else None
            fma = UpbitFullMarketAssignmentService(session)
            fma.get_or_create(
                uba_id,
                strategy_id=strategy_id,
                template_symbol=str(template).upper() if template else None,
            )
            full_market = fma.status_dict(uba_id)
            try:
                from stock_platform.operation.upbit_full_market.portfolio_service import (
                    UpbitPortfolioService,
                )

                drawer = UpbitPortfolioService(session).drawer_summary(uba_id)
                de = drawer.get("daily_entry") if isinstance(drawer, dict) else None
                if isinstance(de, dict):
                    full_market["daily_entry"] = de
                    full_market["daily_entry_label_ko"] = drawer.get(
                        "daily_entry_label_ko"
                    )
            except Exception:  # noqa: BLE001
                pass
            sc = upbit_opportunity_scanner_scheduler.status()
            last = sc.get("last_result_summary") or {}
            cands = last.get("candidates") or []
            scanner_summary = {
                "enabled": sc.get("enabled"),
                "mode": sc.get("mode"),
                "running": sc.get("running"),
                "interval_seconds": sc.get("interval_seconds"),
                "next_run_at": sc.get("next_run_at"),
                "universe_count": last.get("universe_count"),
                "liquidity_pass_count": last.get("liquidity_pass_count"),
                "technical_candidate_count": last.get(
                    "technical_candidate_count"
                ),
                "top_n": last.get("top_n"),
                "candidates": cands[:5],
                "scanner_run_id": last.get("scanner_run_id"),
            }
        elif broker_u == "KIWOOM":
            from stock_platform.trading.kiwoom_funnel_observability import (
                build_kiwoom_funnel_snapshot,
            )

            kiwoom_funnel = build_kiwoom_funnel_snapshot(
                session, user_broker_account_id=uba_id
            )
            full_market = {
                "mode": "FIXED_SYMBOL",
                "full_market_enabled": False,
                "note": "KIWOOM uses strategy FIXED symbol universe (not Upbit scanner)",
                "universe": (kiwoom_funnel or {}).get("universe"),
            }
    except Exception:  # noqa: BLE001
        pass

    open_orders: dict[str, Any] | None = None
    try:
        from stock_platform.order.live_open_order_exposure import (
            evaluate_live_open_order_exposure,
        )
        from stock_platform.risk_engine.resolved_policy import (
            ResolvedRiskPolicyResolver,
        )

        broker = str(uba.broker_code or "").upper() if uba else "UPBIT"
        if broker in {"UPBIT", "KIWOOM"}:
            exp = evaluate_live_open_order_exposure(
                session,
                uba_id=uba_id,
                broker_code=broker,
                environment="LIVE",
            )
            max_open = 1
            if uba is not None:
                pol = ResolvedRiskPolicyResolver(session).resolve(
                    user_id=int(uba.user_id),
                    user_broker_account_id=uba_id,
                )
                max_open = int(pol.max_open_orders)
            open_orders = {
                "total_open_orders": exp.total_open_count,
                "manual_open_orders": exp.manual_open_count,
                "auto_open_orders": exp.auto_open_count,
                "unknown_open_orders": exp.unknown_open_count,
                "auto_open_order_limit": max_open,
                "remote_open_state": exp.remote_state,
                "source": exp.source,
            }
    except Exception:  # noqa: BLE001
        open_orders = None

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
        "full_market": full_market,
        "scanner": scanner_summary,
        "kiwoom_funnel": kiwoom_funnel,
        "filled_exit_with_open_binding": ghost_invariant,
        "open_orders": open_orders,
        "as_of": now.isoformat(),
    }
