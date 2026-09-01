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
    projection: str = "full",
) -> dict[str, Any]:
    """UBA 운영 상태 aggregate.

    projection:
      - full: Admin /ops-status SoT (기본, 의미 변경 금지)
      - daily_report: 일일보고용 slim READ — open-order remote·get_or_create·
        scanner·ghost·master_gate 선행 호출을 생략하고 health snapshot 1회로
        feed/reliability를 채운다. trading gate 자체를 완화하지 않음.
    """

    uba_id = int(user_broker_account_id)
    slim = str(projection or "full").strip().lower() == "daily_report"
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
    broker_u_early = str(getattr(uba, "broker_code", "") or "").upper() if uba else ""
    rt = str(ctrl.get("strategy_runtime") or "STOPPED").upper()
    wk = str(ctrl.get("outbox_worker") or "STOPPED").upper()
    ex = str(ctrl.get("exit_monitor") or "STOPPED").upper()
    # Runner — LIVE signal execution runner (canonical, runtime proxy 아님)
    runner_label = "STOPPED"
    try:
        from stock_platform.trading.autotrading_health_service import (
            _runner_status_for_uba,
        )

        runner_label, _runner_detail = _runner_status_for_uba(
            uba_id=uba_id, broker=broker_u_early or "UPBIT"
        )
    except Exception:  # noqa: BLE001
        runner_label = "RUNNING" if rt == "RUNNING" else "STOPPED"
    runner_running = str(runner_label).upper() == "RUNNING"
    rn = runner_label
    stack_running = sum(
        1
        for x in (
            rt == "RUNNING",
            runner_running,
            wk == "RUNNING",
            ex == "RUNNING",
        )
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
    # daily_report slim: master_gate는 health snapshot 내부에서 1회만 실행
    ai_state = "UNKNOWN"
    broker_u = str(getattr(uba, "broker_code", "") or "").upper() if uba else ""
    ready: dict[str, Any] | None = None
    try:
        if broker_u == "UPBIT":
            if not slim:
                from stock_platform.trading.autotrading_master_gate import (
                    evaluate_uba_autotrading_ready,
                )

                # master_gate는 비용이 큼 — blockers/feed에 1회만 호출해 재사용
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
            else:
                ai_state = "DEFERRED_TO_HEALTH"
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
        if broker_u == "UPBIT" and not slim:
            if ready is None:
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
        elif broker_u == "KIWOOM" and not slim:
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
    # daily_report slim: health invariants가 동일 검사를 수행하므로 중복 생략
    ghost_invariant: dict[str, Any] | None = None
    if broker_u == "UPBIT" and not slim:
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
            # daily_report: UI SoT용 get_or_create(write) 생략 — status READ만
            if not slim:
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
                # UPBIT_SHORT_TERM_OPERATION_V1 observability
                if isinstance(drawer, dict):
                    for key in (
                        "daily_entry_limit",
                        "daily_entry_used",
                        "daily_entry_limit_mode",
                        "auto_slot_limit",
                        "auto_slot_used",
                        "candidate_slot_capacity",
                        "candidate_slot_assigned",
                        "candidate_slot_empty",
                        "auto_position_limit",
                        "auto_position_used",
                        "realtime_monitor_target",
                        "max_positions",
                        "manual_holdings",
                        "unknown_holdings",
                        "account_total_holdings",
                        "position_ownership",
                    ):
                        if key in drawer:
                            full_market[key] = drawer.get(key)
                    # scanner 실측 감시 종목 수 (목표와 별개)
                    try:
                        from stock_platform.operation.upbit_opportunity_scanner.scheduler import (
                            upbit_opportunity_scanner_scheduler,
                        )

                        sc_st = upbit_opportunity_scanner_scheduler.status()
                        last_sum = sc_st.get("last_result_summary") or {}
                        cands = last_sum.get("candidates") or []
                        full_market["realtime_monitored_count"] = (
                            len(cands)
                            if isinstance(cands, list)
                            else last_sum.get("top_n")
                        )
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass
            if not slim:
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
            if slim:
                # funnel은 health snapshot reliability에서 채움
                full_market = {
                    "mode": "FIXED_SYMBOL",
                    "full_market_enabled": False,
                    "note": "KIWOOM uses strategy FIXED symbol universe (not Upbit scanner)",
                }
            else:
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
    # daily_report 화면은 open-order remote exposure를 쓰지 않음
    if not slim:
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
                try:
                    from stock_platform.broker.open_order_gate_classification import (
                        open_order_class_counts_for_ops,
                    )

                    open_orders["OPEN_ORDER_CLASS_COUNTS"] = (
                        open_order_class_counts_for_ops(session, uba_id)
                    )
                except Exception:  # noqa: BLE001
                    open_orders["OPEN_ORDER_CLASS_COUNTS"] = None
        except Exception:  # noqa: BLE001
            open_orders = None
    out = {
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
        "runner": rn,
        "outbox_worker": wk,
        "exit_monitor": ex,
        "runtime_stack": {
            "running_count": stack_running,
            "total": 4,
            "label": f"{stack_running}/4 RUNNING",
            "runtime": rt,
            "runner": rn,
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
    # REAL exit protection vs Shadow research (ops-status SoT)
    try:
        from stock_platform.risk_engine.user_risk_service import (
            UserRiskSettingService,
        )

        risk_svc = UserRiskSettingService(session)
        owner_uid = int(uba.user_id) if uba is not None else None
        resolved = risk_svc.resolve(
            user_id=owner_uid,
            user_broker_account_id=uba_id,
        )
        ep = resolved.exit_protection_summary()
        out["exit_protection"] = ep
        out["exit_policy"] = {
            "MA_DEAD_CROSS": "REAL",
            "STOP_LOSS": (
                "DISABLED"
                if not resolved.stop_loss_effective_enabled
                else "REAL"
            ),
            "TAKE_PROFIT": (
                "DISABLED"
                if not resolved.take_profit_effective_enabled
                else "REAL"
            ),
            "TRAILING": (
                "DISABLED"
                if not resolved.trailing_stop_effective_enabled
                else "REAL"
            ),
            "MAX_HOLD": (
                "DISABLED"
                if not resolved.max_hold_effective_enabled
                else "REAL"
            ),
            "TIME_EXIT": (
                "DISABLED"
                if not resolved.max_hold_effective_enabled
                else "REAL"
            ),
            "rates": {
                "stop_loss_rate": (
                    str(resolved.stop_loss_rate)
                    if resolved.stop_loss_rate is not None
                    else None
                ),
                "take_profit_rate": (
                    str(resolved.take_profit_rate)
                    if resolved.take_profit_rate is not None
                    else None
                ),
                "trailing_stop_rate": (
                    str(resolved.trailing_stop_rate)
                    if resolved.trailing_stop_rate is not None
                    else None
                ),
                "trailing_activation_rate": (
                    str(resolved.trailing_activation_rate)
                    if resolved.trailing_activation_rate is not None
                    else None
                ),
                "max_hold_seconds": resolved.max_hold_seconds,
            },
        }
        # Shadow는 REAL disable과 독립 — 기존 forward collection 유지
        out["exit_shadow"] = {
            "STOP_LOSS": "ACTIVE",
            "TAKE_PROFIT": "ACTIVE",
            "TRAILING": "ACTIVE",
            "TIME_EXIT": "ACTIVE",
            "MAX_HOLD": "ACTIVE",
        }
        out["risk"] = {
            **(out.get("risk") if isinstance(out.get("risk"), dict) else {}),
            "stored": risk_svc.snapshot_account(uba_id),
            "resolved_exit_protection": ep,
            "stop_loss_mode": resolved.stop_loss_mode,
            "take_profit_mode": resolved.take_profit_mode,
            "trailing_stop_mode": resolved.trailing_stop_mode,
            "max_hold_mode": resolved.max_hold_mode,
            "stop_loss_rate": (
                str(resolved.stop_loss_rate)
                if resolved.stop_loss_rate is not None
                else None
            ),
            "take_profit_rate": (
                str(resolved.take_profit_rate)
                if resolved.take_profit_rate is not None
                else None
            ),
            "trailing_stop_rate": (
                str(resolved.trailing_stop_rate)
                if resolved.trailing_stop_rate is not None
                else None
            ),
            "trailing_activation_rate": (
                str(resolved.trailing_activation_rate)
                if resolved.trailing_activation_rate is not None
                else None
            ),
            "max_hold_seconds": resolved.max_hold_seconds,
        }
    except Exception:  # noqa: BLE001
        out.setdefault("exit_policy", {"error": "EXIT_POLICY_RESOLVE_FAILED"})
        out.setdefault("exit_shadow", {"error": "EXIT_SHADOW_STATUS_FAILED"})
    # Canonical reliability health (watchdog SoT)
    try:
        from stock_platform.trading.autotrading_health_service import (
            build_trading_health_snapshot,
        )
        from stock_platform.trading.autotrading_reliability_watchdog import (
            autotrading_reliability_watchdog,
        )

        health = build_trading_health_snapshot(
            session, user_broker_account_id=uba_id, strategy_id=strategy_id
        )
        comps = health.get("components") or {}
        if comps:
            out["runtime"] = str(comps.get("runtime") or out["runtime"])
            out["runner"] = str(comps.get("runner") or out["runner"])
            out["outbox_worker"] = str(comps.get("worker") or out["outbox_worker"])
            out["exit_monitor"] = str(comps.get("exit_monitor") or out["exit_monitor"])
            if health.get("feed_detail"):
                out["market_feed"] = {
                    "status": comps.get("feed") or out["market_feed"].get("status"),
                    "source": out["market_feed"].get("source"),
                    "detail": health.get("feed_detail"),
                }
            rs = out["runtime_stack"]
            rs["runtime"] = out["runtime"]
            rs["runner"] = out["runner"]
            rs["outbox_worker"] = out["outbox_worker"]
            rs["exit_monitor"] = out["exit_monitor"]
            rs["running_count"] = sum(
                1
                for k in ("runtime", "runner", "outbox_worker", "exit_monitor")
                if str(rs.get(k)).upper() == "RUNNING"
            )
            rs["label"] = f"{rs['running_count']}/4 RUNNING"
        out["reliability"] = {
            "health_state": health.get("health_state"),
            "health_reasons": health.get("health_reasons"),
            "partial_restore": health.get("partial_restore"),
            "auto_trading_ready": health.get("auto_trading_ready"),
            "first_zero_stage": health.get("first_zero_stage"),
            "first_zero_reason": health.get("first_zero_reason"),
            "no_trade_classification": health.get("no_trade_classification"),
            "no_trade_detail": health.get("no_trade_detail"),
            "waiting_starvation": health.get("waiting_starvation"),
            "waiting_count": health.get("waiting_count"),
            "empty_count": health.get("empty_count"),
            "heartbeats": health.get("heartbeats"),
            "invariants": health.get("invariants"),
            "funnel": health.get("funnel"),
            "watchdog": autotrading_reliability_watchdog.status(),
        }
        out["auto_trading_ready"] = health.get("auto_trading_ready")
        # slim KIWOOM: funnel을 ops 루트에도 복사 (장후 분류용)
        if slim and broker_u == "KIWOOM" and isinstance(health.get("funnel"), dict):
            out["kiwoom_funnel"] = health.get("funnel")
        if slim:
            out["projection"] = "daily_report"
            # health 컴포넌트에서 AI 상태 보강 (master_gate 선행 생략 시)
            if broker_u == "UPBIT" and out.get("ai_state") == "DEFERRED_TO_HEALTH":
                ai_gate = (health.get("checks") or {}).get("ai_gate") if isinstance(
                    health.get("checks"), dict
                ) else None
                if not ai_gate and isinstance(health.get("ai_gate"), dict):
                    ai_gate = health.get("ai_gate")
                if isinstance(ai_gate, dict):
                    out["ai_state"] = str(
                        ai_gate.get("assumed_result")
                        or ai_gate.get("recommendation")
                        or "HOLD"
                    ).upper()
    except Exception:  # noqa: BLE001
        out["reliability"] = {"error": "HEALTH_SNAPSHOT_FAILED"}

    # ARM/Activation expiry+renew 스캔 runtime 관측 (주문 유발 없음)
    try:
        from stock_platform.trading.live_session_expiry_runtime import (
            live_session_expiry_runtime,
        )

        out["session_expiry"] = live_session_expiry_runtime.status()
    except Exception:  # noqa: BLE001
        out["session_expiry"] = {"error": "SESSION_EXPIRY_STATUS_UNAVAILABLE"}

    # ARM renew / exit spam observability (operational safety hardening)
    try:
        unatt = out.get("unattended") if isinstance(out.get("unattended"), dict) else {}
        last_arm = (
            unatt.get("last_arm_renew_attempt")
            if isinstance(unatt.get("last_arm_renew_attempt"), dict)
            else {}
        )
        out["ARM_RENEW_BLOCK_REASON"] = (
            last_arm.get("arm_renew_skipped")
            or last_arm.get("arm_renew_error")
        )
    except Exception:  # noqa: BLE001
        out["ARM_RENEW_BLOCK_REASON"] = None
    try:
        from stock_platform.position.exit_monitor_runtime import (
            position_exit_monitor_manager,
        )

        em_st = position_exit_monitor_manager.status()
        out["EXIT_SUBMISSION_SUPPRESSED"] = int(
            em_st.get("EXIT_SUBMISSION_SUPPRESSED") or 0
        )
        out["EXIT_SUPPRESSION_REASON"] = em_st.get("EXIT_SUPPRESSION_REASON")
    except Exception:  # noqa: BLE001
        out["EXIT_SUBMISSION_SUPPRESSED"] = 0
        out["EXIT_SUPPRESSION_REASON"] = None

    return out


def build_uba_daily_report_ops_projection(
    session: Session,
    *,
    user_broker_account_id: int,
    strategy_id: int | None = None,
) -> dict[str, Any]:
    """일일보고 전용 ops projection — /ops-status full SoT와 분리."""

    return build_uba_operational_summary(
        session,
        user_broker_account_id=user_broker_account_id,
        strategy_id=strategy_id,
        projection="daily_report",
    )
