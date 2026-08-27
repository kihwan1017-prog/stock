"""Canonical autotrading health SoT — UPBIT/KIWOOM per-UBA snapshot."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_platform.broker.live_transition_service import LiveTradingTransitionService
from stock_platform.common.settings import get_settings
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.autotrading_health_slo import load_autotrading_health_slo
from stock_platform.trading.autotrading_no_trade_classification import (
    classify_no_trade_status,
)
from stock_platform.trading.live_session_expiry import (
    activation_remaining_seconds,
    aware_utc,
)
from stock_platform.trading.live_unattended_authorization_service import (
    LiveUnattendedAuthorizationService,
)
from stock_platform.trading.upbit_24x7_control import combined_control_status

HEALTH_READY = "READY"
HEALTH_DEGRADED = "DEGRADED"
HEALTH_BROKEN = "BROKEN"


def _lifecycle(label: str) -> str:
    return str(label or "STOPPED").upper()


def _age_seconds(ts: datetime | timedelta | None, *, now: datetime) -> float | None:
    if ts is None:
        return None
    if isinstance(ts, timedelta):
        return max(0.0, ts.total_seconds())
    if not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (now - ts).total_seconds())


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return aware_utc(value)
    try:
        return aware_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except Exception:  # noqa: BLE001
        return None


def _runner_status_for_uba(*, uba_id: int, broker: str) -> tuple[str, dict[str, Any]]:
    """LIVE signal execution runner — control-plane runner SoT."""

    try:
        from stock_platform.realtime.runtime import (
            realtime_execution_runner_manager,
        )

        runner = realtime_execution_runner_manager.get(uba_id, broker)
        if runner is None:
            return "STOPPED", {"running": False, "reason": "NO_RUNNER"}
        st = runner.status() or {}
        running = bool(st.get("running"))
        return ("RUNNING" if running else "STOPPED"), st
    except Exception as exc:  # noqa: BLE001
        return "STOPPED", {"error": type(exc).__name__}


def _resolve_stack_components(
    *,
    broker: str,
    uba_id: int,
    ctrl: dict[str, Any],
    strategy_id: int | None = None,
) -> dict[str, Any]:
    """실행 스택 component — /health/ops(upbit_24x7)와 동일 process SoT."""

    runner_st, runner_detail = _runner_status_for_uba(uba_id=uba_id, broker=broker)
    runtime_detail = ctrl.get("runtime") or {}
    worker_detail = ctrl.get("worker") or {}
    exit_detail = ctrl.get("exit_monitor_detail") or {}

    runtime_st = _lifecycle(ctrl.get("strategy_runtime"))
    worker_st = _lifecycle(ctrl.get("outbox_worker"))
    exit_st = _lifecycle(ctrl.get("exit_monitor"))
    ops24: dict[str, Any] | None = None

    if broker == "UPBIT":
        try:
            from stock_platform.trading.upbit_24x7_control import (
                build_24x7_ops_health,
                runtime_status_for_uba,
            )

            ops24 = build_24x7_ops_health()
            worker_st = _lifecycle(
                (ops24.get("live_outbox_worker") or {}).get("status")
            )
            exit_st = _lifecycle(
                (ops24.get("live_exit_monitor") or {}).get("status")
            )
            runtime_ub = runtime_status_for_uba(
                user_broker_account_id=uba_id,
                strategy_id=strategy_id,
                broker_code=broker,
            )
            runtime_st = _lifecycle(runtime_ub.get("status"))
            if runtime_st == "STOPPED":
                runtime_st = _lifecycle(
                    (ops24.get("strategy_runtime") or {}).get("status")
                )
            runtime_detail = runtime_ub
            worker_detail = ops24.get("live_outbox_worker") or worker_detail
            exit_detail = ops24.get("live_exit_monitor") or exit_detail
        except Exception as exc:  # noqa: BLE001
            ops24 = {"error": type(exc).__name__}

    return {
        "runtime": runtime_st,
        "runner": runner_st,
        "worker": worker_st,
        "exit_monitor": exit_st,
        "runner_detail": runner_detail,
        "runtime_detail": runtime_detail,
        "worker_detail": worker_detail,
        "exit_detail": exit_detail,
        "ops24": ops24,
    }


def _collect_heartbeats(
    session: Session,
    *,
    uba_id: int,
    broker: str,
    ctrl: dict[str, Any],
    stack: dict[str, Any],
    runner_detail: dict[str, Any],
    feed_detail: dict[str, Any],
    slo: Any,
    now: datetime,
) -> dict[str, Any]:
    """실제 activity 기반 heartbeat (task exists만으로 RUNNING 판정 금지)."""

    hb: dict[str, Any] = {}

    rt = stack.get("runtime_detail") or ctrl.get("runtime") or {}
    hb["runtime_last_heartbeat_at"] = rt.get("last_heartbeat_at")
    hb["runtime_heartbeat_age_seconds"] = _age_seconds(
        _parse_iso(rt.get("last_heartbeat_at")), now=now
    )

    hb["runner_last_heartbeat_at"] = runner_detail.get("heartbeat")
    hb["runner_heartbeat_age_seconds"] = _age_seconds(
        _parse_iso(runner_detail.get("heartbeat")), now=now
    )

    worker = stack.get("worker_detail") or ctrl.get("worker") or {}
    hb["worker_last_run_at"] = worker.get("last_run_at")
    hb["worker_heartbeat_age_seconds"] = _age_seconds(
        _parse_iso(worker.get("last_run_at")), now=now
    )

    exit_d = stack.get("exit_detail") or ctrl.get("exit_monitor_detail") or {}
    hb["exit_monitor_last_heartbeat_at"] = exit_d.get("last_evaluated_at")
    hb["exit_last_evaluation_at"] = exit_d.get("last_evaluated_at")
    hb["exit_heartbeat_age_seconds"] = _age_seconds(
        _parse_iso(exit_d.get("last_evaluated_at")), now=now
    )

    hb["feed_last_event_at"] = (
        feed_detail.get("last_received_at")
        or feed_detail.get("last_event_at")
        or (feed_detail.get("detail") or {}).get("last_received_at")
    )
    hb["feed_age_seconds"] = feed_detail.get("age_seconds")
    if hb["feed_age_seconds"] is None:
        hb["feed_age_seconds"] = _age_seconds(
            _parse_iso(hb["feed_last_event_at"]), now=now
        )

    try:
        from stock_platform.operation.upbit_opportunity_scanner.scheduler import (
            upbit_opportunity_scanner_scheduler,
        )

        sc = upbit_opportunity_scanner_scheduler.status()
        hb["scanner_last_started_at"] = sc.get("last_run_at")
        hb["scanner_last_completed_at"] = sc.get("last_completed_at")
        hb["scanner_last_success_at"] = sc.get("last_success_at")
        hb["scanner_run_count"] = sc.get("run_count")
    except Exception:  # noqa: BLE001
        pass

    if broker == "UPBIT":
        try:
            from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
                portfolio_entry_telemetry,
            )

            telem = portfolio_entry_telemetry.snapshot(uba_id) or {}
            latest_eval = None
            for sym_data in telem.values():
                if not isinstance(sym_data, dict):
                    continue
                ts = _parse_iso(sym_data.get("last_evaluated_at"))
                if ts and (latest_eval is None or ts > latest_eval):
                    latest_eval = ts
            if latest_eval:
                hb["entry_last_evaluated_at"] = latest_eval.isoformat()
        except Exception:  # noqa: BLE001
            pass

        last_sel = session.scalar(
            text(
                """
                SELECT MAX(created_at) FROM operation.upbit_live_candidate_selection
                WHERE user_broker_account_id = :uba
                """
            ),
            {"uba": uba_id},
        )
        last_wait = session.scalar(
            text(
                """
                SELECT MAX(updated_at) FROM operation.upbit_position_slot
                WHERE user_broker_account_id = :uba AND status = 'WAITING_SIGNAL'
                """
            ),
            {"uba": uba_id},
        )
        oldest_wait = session.scalar(
            text(
                """
                SELECT MIN(created_at)
                FROM operation.upbit_position_slot
                WHERE user_broker_account_id = :uba AND status = 'WAITING_SIGNAL'
                """
            ),
            {"uba": uba_id},
        )
        try:
            from stock_platform.operation.upbit_full_market.waiting_lifecycle import (
                oldest_waiting_age_seconds,
            )

            wl_oldest: float | None = oldest_waiting_age_seconds(
                session, user_broker_account_id=uba_id, now=now
            )
            if wl_oldest is not None:
                hb["oldest_waiting_age_seconds"] = round(wl_oldest, 1)
        except Exception:  # noqa: BLE001
            wl_oldest = None
        last_ord = session.scalar(
            text(
                """
                SELECT MAX(created_at) FROM trading.trading_order
                WHERE user_broker_account_id = :uba AND broker_code = 'UPBIT'
                """
            ),
            {"uba": uba_id},
        )
        hb["selection_last_created_at"] = (
            aware_utc(last_sel).isoformat() if last_sel else None
        )
        hb["waiting_last_updated_at"] = (
            aware_utc(last_wait).isoformat() if last_wait else None
        )
        if wl_oldest is None and oldest_wait is not None:
            ow = aware_utc(oldest_wait)
            if ow is not None:
                hb["oldest_waiting_age_seconds"] = round(
                    max(0.0, (now - ow).total_seconds()), 1
                )
        hb["order_last_created_at"] = (
            aware_utc(last_ord).isoformat() if last_ord else None
        )

    hb["slo"] = {
        "feed_max_age_seconds": slo.feed_max_age_seconds,
        "scanner_max_age_seconds": slo.scanner_max_age_seconds,
        "runner_heartbeat_max_age_seconds": slo.runner_heartbeat_max_age_seconds,
        "worker_heartbeat_max_age_seconds": slo.worker_heartbeat_max_age_seconds,
        "exit_heartbeat_max_age_seconds": slo.exit_monitor_heartbeat_max_age_seconds,
    }
    return hb


def _slot_counts(session: Session, *, uba_id: int) -> dict[str, int]:
    rows = session.execute(
        text(
            """
            SELECT status, COUNT(*) AS n
            FROM operation.upbit_position_slot
            WHERE user_broker_account_id = :uba
            GROUP BY status
            """
        ),
        {"uba": uba_id},
    ).mappings().all()
    counts = {str(r["status"]): int(r["n"]) for r in rows}
    open_n = counts.get("OPEN", 0)
    waiting_n = counts.get("WAITING_SIGNAL", 0)
    empty_n = counts.get("EMPTY", 0)
    max_slots = 5
    return {
        "open_count": open_n,
        "waiting_count": waiting_n,
        "empty_count": empty_n,
        "free_slot_count": max(0, max_slots - open_n - waiting_n),
    }


def _invariants(session: Session, *, uba_id: int, broker: str) -> dict[str, Any]:
    inv: dict[str, Any] = {
        "OPEN_SLOT_WITHOUT_OPEN_BINDING": 0,
        "EMPTY_SLOT_WITH_OPEN_BINDING": 0,
        "WAITING_SLOT_WITHOUT_SELECTION": 0,
        "WAITING_SLOT_STALLED": 0,
        "FILLED_EXIT_WITH_OPEN_BINDING": 0,
    }
    if broker != "UPBIT":
        return inv
    try:
        open_no_bind = session.scalar(
            text(
                """
                SELECT COUNT(*) FROM operation.upbit_position_slot
                WHERE user_broker_account_id = :uba AND status = 'OPEN'
                  AND position_binding_id IS NULL
                """
            ),
            {"uba": uba_id},
        )
        inv["OPEN_SLOT_WITHOUT_OPEN_BINDING"] = int(open_no_bind or 0)
    except Exception:  # noqa: BLE001
        pass
    try:
        from stock_platform.broker.upbit.filled_exit_finalizer import (
            detect_filled_exit_with_open_binding,
        )

        ghost = detect_filled_exit_with_open_binding(
            session, user_broker_account_id=uba_id
        )
        inv["FILLED_EXIT_WITH_OPEN_BINDING"] = int(ghost.get("count") or 0)
    except Exception:  # noqa: BLE001
        pass
    return inv


def _kiwoom_session_allows_stack_slo(session: Session, *, now: datetime) -> bool:
    try:
        from stock_platform.trading.market_hours_authorization import (
            krx_market_hours_state,
        )

        mh = krx_market_hours_state(session, now=now)
        return bool(mh.get("in_regular_session"))
    except Exception:  # noqa: BLE001
        return False


def build_trading_health_snapshot(
    session: Session,
    *,
    user_broker_account_id: int,
    strategy_id: int | None = None,
) -> dict[str, Any]:
    """TradingHealthSnapshot — canonical health SoT."""

    uba_id = int(user_broker_account_id)
    uba = session.get(UserBrokerAccount, uba_id)
    broker = str(getattr(uba, "broker_code", "") or "").upper() if uba else ""
    now = datetime.now(timezone.utc)
    slo = load_autotrading_health_slo()

    if uba is None:
        return {
            "ok": False,
            "reason": "UBA_NOT_FOUND",
            "user_broker_account_id": uba_id,
        }

    ctrl = combined_control_status(
        session,
        user_broker_account_id=uba_id,
        strategy_id=strategy_id,
    )
    stack = _resolve_stack_components(
        broker=broker,
        uba_id=uba_id,
        ctrl=ctrl,
        strategy_id=strategy_id,
    )
    runtime_st = stack["runtime"]
    worker_st = stack["worker"]
    exit_st = stack["exit_monitor"]
    runner_st = stack["runner"]
    runner_detail = stack["runner_detail"]

    live_on = bool(getattr(uba, "live_order_enabled", False))
    arm_exp = aware_utc(getattr(uba, "arm_expires_at", None))
    arm_on = bool(getattr(uba, "live_armed", False)) and (
        arm_exp is None or arm_exp > now
    )
    act = LiveTradingTransitionService(session).peek_active(
        broker_code=broker, user_broker_account_id=uba_id
    )
    activation_active = act is not None

    # Feed — broker별 SoT (KIWOOM: market realtime runtime / UPBIT: master gate)
    feed_status = "UNKNOWN"
    feed_detail: dict[str, Any] = {}
    blockers: list[str] = []
    try:
        if broker == "KIWOOM":
            from stock_platform.realtime.kiwoom_market_realtime_runtime import (
                kiwoom_market_realtime_runtime as kmr,
            )

            st = kmr.status()
            running = bool(st.get("running"))
            connected = bool(st.get("connected"))
            age = st.get("feed_age_seconds")
            feed_detail = {
                "ok": bool(running and connected),
                "running": running,
                "connected": connected,
                "age_seconds": age,
                "last_received_at": st.get("last_tick_at"),
                "symbols": ((st.get("client") or {}) or {}).get("symbols"),
                "subscription_count": ((st.get("client") or {}) or {}).get(
                    "subscription_count"
                ),
                "last_error": ((st.get("client") or {}) or {}).get("last_error"),
                "process_market_environment": st.get(
                    "process_market_environment"
                ),
                "execution_process_kiwoom_use_mock": st.get(
                    "execution_process_kiwoom_use_mock"
                ),
                "source": "KIWOOM_MARKET_REALTIME",
                "policy": "BLOCK_IF_UNHEALTHY_FOR_AUTO_LIVE",
                "evaluator_path": "KiwoomMarketWS→QuoteBus→MovingAverageStrategyEvaluator",
            }
            if running and connected:
                if age is not None and float(age) > slo.feed_max_age_seconds:
                    feed_status = "STALE"
                    feed_detail["ok"] = False
                    feed_detail["reason"] = "TICK_STALE"
                else:
                    feed_status = "REAL_FRESH"
                    feed_detail["reason"] = "OK"
            elif running and not connected:
                feed_status = "CONNECTING"
                feed_detail["reason"] = "RUNNING_NOT_CONNECTED"
            else:
                feed_status = "DISCONNECTED"
                feed_detail["reason"] = "FEED_NOT_RUNNING"
            if not feed_detail.get("ok"):
                blockers.append("MARKET_FEED_UNHEALTHY")
        else:
            from stock_platform.trading.autotrading_master_gate import (
                evaluate_uba_autotrading_ready,
            )
            from stock_platform.trading.uba_operational_summary import (
                _map_market_feed_status,
            )

            ready = evaluate_uba_autotrading_ready(
                session, user_broker_account_id=uba_id
            )
            feed_detail = (ready.get("checks") or {}).get("market_feed") or {}
            feed_status = _map_market_feed_status(feed_detail)
            for b in ready.get("blockers") or []:
                code = str(b)
                if code and code not in blockers:
                    blockers.append(code)
    except Exception as exc:  # noqa: BLE001
        feed_detail = {"error": type(exc).__name__}

    # Scanner — UPBIT opportunity scanner / KIWOOM 은 runtime MA path 가 scanner 역할
    scanner_st = "STOPPED"
    scanner_detail: dict[str, Any] = {}
    try:
        if broker == "KIWOOM":
            # FIXED-symbol MA evaluator 는 runtime 에 종속 (Upbit scanner 혼용 금지)
            if runtime_st == "RUNNING":
                scanner_st = "RUNNING"
                scanner_detail = {
                    "mode": "KIWOOM_FIXED_SYMBOL_MA",
                    "note": "Upbit opportunity scanner not used",
                    "running": True,
                }
            else:
                scanner_detail = {
                    "mode": "KIWOOM_FIXED_SYMBOL_MA",
                    "running": False,
                    "reason": "RUNTIME_NOT_RUNNING",
                }
        else:
            from stock_platform.operation.upbit_opportunity_scanner.scheduler import (
                upbit_opportunity_scanner_scheduler,
            )

            scanner_detail = upbit_opportunity_scanner_scheduler.status()
            if bool(scanner_detail.get("running")) or bool(
                scanner_detail.get("started")
            ):
                scanner_st = "RUNNING"
    except Exception:  # noqa: BLE001
        pass

    heartbeats = _collect_heartbeats(
        session,
        uba_id=uba_id,
        broker=broker,
        ctrl=ctrl,
        stack=stack,
        runner_detail=runner_detail,
        feed_detail=feed_detail,
        slo=slo,
        now=now,
    )

    slots = _slot_counts(session, uba_id=uba_id) if broker == "UPBIT" else {
        "open_count": 0,
        "waiting_count": 0,
        "empty_count": 0,
        "free_slot_count": 0,
    }
    invariants = _invariants(session, uba_id=uba_id, broker=broker)

    daily: dict[str, Any] = {}
    if broker == "UPBIT":
        try:
            from stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission import (
                resolve_portfolio_daily_entry_limit,
            )
            from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
                summarize_portfolio_daily_entries,
            )

            lim = resolve_portfolio_daily_entry_limit(session, uba_id)
            daily = summarize_portfolio_daily_entries(session, uba_id, daily_limit=lim)
        except Exception:  # noqa: BLE001
            daily = {}

    # PARTIAL_RESTORE — LIVE+ARM+Activation valid but stack component STOPPED
    stack_down = any(
        st != "RUNNING"
        for st in (runtime_st, runner_st, worker_st, exit_st)
    )
    partial_restore = (
        live_on
        and arm_on
        and activation_active
        and stack_down
        and broker == "UPBIT"
    )

    kiwoom_stack_slo = (
        _kiwoom_session_allows_stack_slo(session, now=now)
        if broker == "KIWOOM"
        else True
    )

    feed_healthy = feed_status in {"REAL_FRESH", "FRESH", "CONNECTED", "HEALTHY", "OK"}
    feed_age = heartbeats.get("feed_age_seconds")
    if feed_age is not None and float(feed_age) > slo.feed_max_age_seconds:
        feed_healthy = False

    # Health state
    health_state = HEALTH_READY
    health_reasons: list[str] = []

    if not live_on or not arm_on or not activation_active:
        health_state = HEALTH_DEGRADED
        health_reasons.append("LIVE_ARM_ACTIVATION_INCOMPLETE")
    elif partial_restore:
        health_state = HEALTH_BROKEN
        health_reasons.append("PARTIAL_RESTORE")
    elif int(invariants.get("FILLED_EXIT_WITH_OPEN_BINDING") or 0) > 0:
        health_state = HEALTH_BROKEN
        health_reasons.append("GHOST_OPEN_BINDING")
    elif slots.get("open_count", 0) > 0 and exit_st != "RUNNING":
        health_state = HEALTH_BROKEN
        health_reasons.append("EXIT_DOWN_WITH_OPEN_POSITION")
    elif broker == "UPBIT" and stack_down and kiwoom_stack_slo:
        health_state = HEALTH_BROKEN
        health_reasons.append("EXECUTION_STACK_DOWN")
    elif not feed_healthy and broker == "UPBIT":
        health_state = HEALTH_BROKEN
        health_reasons.append("FEED_UNHEALTHY")
    elif (
        not feed_healthy
        and broker == "KIWOOM"
        and kiwoom_stack_slo
        and live_on
        and arm_on
        and activation_active
    ):
        health_state = HEALTH_BROKEN
        health_reasons.append("FEED_UNHEALTHY")
    elif blockers:
        health_state = HEALTH_DEGRADED
        health_reasons.append("MASTER_GATE_BLOCKERS")

    # Funnel + FIRST_ZERO
    funnel: dict[str, Any] | None = None
    first_zero_stage = None
    first_zero_reason = None
    no_trade: dict[str, Any] = {}
    waiting_starvation: dict[str, Any] = {}
    max_pos = 5
    oldest_age: float | None = None
    if broker == "UPBIT":
        from stock_platform.trading.upbit_funnel_observability import (
            build_upbit_funnel_snapshot,
        )

        funnel = build_upbit_funnel_snapshot(
            session,
            user_broker_account_id=uba_id,
            window_minutes=slo.funnel_window_minutes,
        )
        first_zero_stage = funnel.get("first_zero_stage")
        first_zero_reason = funnel.get("first_zero_reason")

        from stock_platform.operation.upbit_full_market.waiting_lifecycle import (
            detect_waiting_slot_starvation,
            load_waiting_lifecycle_policy,
        )
        from stock_platform.operation.upbit_full_market.entities import (
            UpbitPortfolioPolicyEntity,
        )

        pol_row = session.scalar(
            select(UpbitPortfolioPolicyEntity).where(
                UpbitPortfolioPolicyEntity.user_broker_account_id == uba_id
            )
        )
        rg = dict(getattr(pol_row, "risk_group_policy_json", None) or {})
        wl_policy = load_waiting_lifecycle_policy(
            settings=get_settings(),
            risk_group_policy_json=rg,
        )
        max_pos = int(getattr(pol_row, "max_positions", None) or 5)
        oldest_age = heartbeats.get("oldest_waiting_age_seconds")
        if oldest_age is not None:
            oldest_age = float(oldest_age)
        stack_ready_for_starvation = (
            not partial_restore
            and runtime_st == "RUNNING"
            and worker_st == "RUNNING"
            and exit_st == "RUNNING"
            and feed_healthy
            and scanner_st == "RUNNING"
        )
        waiting_starvation = detect_waiting_slot_starvation(
            waiting_count=int(slots.get("waiting_count") or 0),
            empty_count=int(slots.get("empty_count") or 0),
            max_positions=max_pos,
            quota_remaining=int(daily.get("remaining") or 0),
            stack_ready=stack_ready_for_starvation,
            oldest_waiting_age_seconds=oldest_age,
            order_count_window=int((funnel or {}).get("stages", {}).get("ORDER", 0)),
            candidate_or_selection_active=(
                int((funnel or {}).get("stages", {}).get("CANDIDATE", 0)) > 0
                or int((funnel or {}).get("stages", {}).get("SELECTION", 0)) > 0
            ),
            policy=wl_policy,
        )
        if waiting_starvation.get("waiting_slot_starvation"):
            esc = str(waiting_starvation.get("escalation") or "NONE")
            if esc == "BROKEN":
                if health_state == HEALTH_READY:
                    health_state = HEALTH_BROKEN
                health_reasons.append("WAITING_SLOT_STARVATION_BROKEN")
            elif esc == "DEGRADED" and health_state == HEALTH_READY:
                health_state = HEALTH_DEGRADED
                health_reasons.append("WAITING_SLOT_STARVATION")
    elif broker == "KIWOOM":
        from stock_platform.trading.kiwoom_funnel_observability import (
            build_kiwoom_funnel_snapshot,
        )

        funnel = build_kiwoom_funnel_snapshot(
            session, user_broker_account_id=uba_id
        )
        first_zero_stage = funnel.get("first_zero_stage")
        first_zero_reason = (funnel.get("reasons") or [None])[0]

    no_trade = classify_no_trade_status(
        health_state=health_state,
        partial_restore=partial_restore,
        stack_components_down=stack_down,
        daily_blocking=bool(daily.get("blocking")),
        free_slots=int(slots.get("free_slot_count") or 0),
        waiting_count=int(slots.get("waiting_count") or 0),
        max_positions=max_pos,
        selection_count_window=int((funnel or {}).get("stages", {}).get("SELECTION", 0)),
        candidate_count_window=int((funnel or {}).get("stages", {}).get("CANDIDATE", 0)),
        order_count_window=int((funnel or {}).get("stages", {}).get("ORDER", 0)),
        admission_count_window=int((funnel or {}).get("stages", {}).get("ADMISSION", 0)),
        feed_healthy=feed_healthy,
        scanner_active=scanner_st == "RUNNING",
        pipeline_stall_minutes=slo.pipeline_stall_minutes,
        last_order_at=_parse_iso(heartbeats.get("order_last_created_at")),
        last_selection_at=_parse_iso(heartbeats.get("selection_last_created_at")),
        waiting_slot_starvation=bool(
            waiting_starvation.get("waiting_slot_starvation")
        ),
        starvation_escalation=str(waiting_starvation.get("escalation") or "NONE"),
        oldest_waiting_age_seconds=oldest_age,
        now=now,
    )
    if broker == "UPBIT" and isinstance(funnel, dict):
        from stock_platform.trading.pipeline_liveness_service import (
            classify_with_entry_signal_context,
        )

        stg = funnel.get("stages") or {}
        no_trade = classify_with_entry_signal_context(
            base_kwargs={
                "health_state": health_state,
                "partial_restore": partial_restore,
                "stack_components_down": stack_down,
                "daily_blocking": bool(daily.get("blocking")),
                "free_slots": int(slots.get("free_slot_count") or 0),
                "waiting_count": int(slots.get("waiting_count") or 0),
                "max_positions": max_pos,
                "selection_count_window": int(stg.get("SELECTION") or 0),
                "candidate_count_window": int(stg.get("CANDIDATE") or 0),
                "order_count_window": int(stg.get("ORDER") or 0),
                "admission_count_window": int(stg.get("ADMISSION") or 0),
                "feed_healthy": feed_healthy,
                "scanner_active": scanner_st == "RUNNING",
                "pipeline_stall_minutes": slo.pipeline_stall_minutes,
                "last_order_at": _parse_iso(heartbeats.get("order_last_created_at")),
                "last_selection_at": _parse_iso(
                    heartbeats.get("selection_last_created_at")
                ),
                "waiting_slot_starvation": bool(
                    waiting_starvation.get("waiting_slot_starvation")
                ),
                "starvation_escalation": str(
                    waiting_starvation.get("escalation") or "NONE"
                ),
                "oldest_waiting_age_seconds": oldest_age,
                "now": now,
            },
            entry_eval_count=int(stg.get("ENTRY_EVALUATION") or 0),
            entry_pass_count=int(stg.get("ENTRY_PASS") or 0),
            entry_pending_stuck=int(stg.get("ENTRY_PENDING_STUCK") or 0),
            top_block_reason=funnel.get("top_entry_block_reason"),
        )
        # stuck pending은 health도 DEGRADED 이상으로
        if int(stg.get("ENTRY_PENDING_STUCK") or 0) > 0:
            if health_state == HEALTH_READY:
                health_state = HEALTH_DEGRADED
            if "ENTRY_PENDING_ZERO_FILL_STUCK" not in health_reasons:
                health_reasons.append("ENTRY_PENDING_ZERO_FILL_STUCK")


    auto_trading_ready = (
        health_state == HEALTH_READY
        and not partial_restore
        and not bool(daily.get("blocking"))
        and len(blockers) == 0
    )

    return {
        "ok": True,
        "schema": "trading_health_snapshot_v1",
        "market": broker,
        "user_broker_account_id": uba_id,
        "updated_at": now.isoformat(),
        "process_status": "UP" if broker else "UNKNOWN",
        "live": "ON" if live_on else "OFF",
        "arm": "ON" if arm_on else "OFF",
        "activation": "ACTIVE" if activation_active else "INACTIVE",
        "components": {
            "runtime": runtime_st,
            "runner": runner_st,
            "worker": worker_st,
            "exit_monitor": exit_st,
            "scanner": scanner_st,
            "feed": feed_status,
        },
        "heartbeats": heartbeats,
        "daily_count": daily.get("entry_count"),
        "daily_limit": daily.get("entry_limit"),
        "daily_remaining": daily.get("remaining"),
        "daily_blocking": daily.get("blocking"),
        "open_count": slots.get("open_count"),
        "waiting_count": slots.get("waiting_count"),
        "empty_count": slots.get("empty_count"),
        "free_slot_count": slots.get("free_slot_count"),
        "waiting_starvation": waiting_starvation,
        "first_zero_stage": first_zero_stage,
        "first_zero_reason": first_zero_reason,
        "funnel": funnel,
        "no_trade_classification": no_trade.get("classification"),
        "no_trade_detail": no_trade,
        "health_state": health_state,
        "health_reasons": health_reasons,
        "partial_restore": partial_restore,
        "auto_trading_ready": auto_trading_ready,
        "blockers": blockers,
        "invariants": invariants,
        "kiwoom_stack_slo_active": kiwoom_stack_slo,
        "scanner_detail": scanner_detail,
        "runner_detail": runner_detail,
        "feed_detail": feed_detail,
        "control_plane": {
            "strategy_runtime": runtime_st,
            "outbox_worker": worker_st,
            "exit_monitor": exit_st,
            "runner": runner_st,
            "ops24": stack.get("ops24"),
        },
    }


def build_autotrading_health_overview(
    session: Session,
    *,
    uba_ids: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Admin health API — UPBIT + KIWOOM."""

    ids = uba_ids or {"UPBIT": 1380, "KIWOOM": 1381}
    markets: dict[str, Any] = {}
    for market, uba_id in ids.items():
        snap = build_trading_health_snapshot(
            session, user_broker_account_id=int(uba_id)
        )
        markets[market] = snap
    return {
        "ok": True,
        "schema": "autotrading_health_overview_v1",
        "markets": markets,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
