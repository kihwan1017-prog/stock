"""UPBIT REAL autotrading funnel + FIRST_ZERO_STAGE (READ)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.trading.account_models import UserBrokerAccount

UPBIT_FUNNEL_STAGES = (
    "FEED",
    "SCANNER",
    "CANDIDATE",
    "ANALYSIS",
    "SELECTION",
    "WAITING",
    "ENTRY_EVALUATION",
    "ENTRY_PASS",
    "ADMISSION",
    "ORDER",
    "FILL",
)


def build_upbit_funnel_snapshot(
    session: Session,
    *,
    user_broker_account_id: int,
    window_minutes: float = 15.0,
) -> dict[str, Any]:
    """Rolling window funnel counts + FIRST_ZERO."""

    uba_id = int(user_broker_account_id)
    uba = session.get(UserBrokerAccount, uba_id)
    broker = str(getattr(uba, "broker_code", "") or "").upper() if uba else ""
    if broker != "UPBIT":
        return {
            "ok": False,
            "reason": "NOT_UPBIT_UBA",
            "user_broker_account_id": uba_id,
        }

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=max(1.0, float(window_minutes)))

    from stock_platform.trading.upbit_24x7_control import combined_control_status

    ctrl = combined_control_status(session, user_broker_account_id=uba_id)

    sel_n = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM operation.upbit_live_candidate_selection
            WHERE user_broker_account_id = :uba AND created_at >= :ws
            """
        ),
        {"uba": uba_id, "ws": window_start},
    )
    analysis_n = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM operation.upbit_llm_context_analysis
            WHERE created_at >= :ws
            """
        ),
        {"ws": window_start},
    )
    opp_n = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM trading.upbit_opportunity_shadow
            WHERE created_at >= :ws
            """
        ),
        {"ws": window_start},
    )
    buy_orders = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM trading.trading_order
            WHERE user_broker_account_id = :uba AND broker_code = 'UPBIT'
              AND side_code = 'BUY' AND created_at >= :ws
            """
        ),
        {"uba": uba_id, "ws": window_start},
    )
    buy_fills = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM trading.trading_order
            WHERE user_broker_account_id = :uba AND broker_code = 'UPBIT'
              AND side_code = 'BUY' AND status_code = 'FILLED'
              AND COALESCE(filled_at, created_at) >= :ws
            """
        ),
        {"uba": uba_id, "ws": window_start},
    )

    waiting_n = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM operation.upbit_position_slot
            WHERE user_broker_account_id = :uba AND status = 'WAITING_SIGNAL'
            """
        ),
        {"uba": uba_id},
    )
    open_n = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM operation.upbit_position_slot
            WHERE user_broker_account_id = :uba AND status = 'OPEN'
            """
        ),
        {"uba": uba_id},
    )
    empty_n = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM operation.upbit_position_slot
            WHERE user_broker_account_id = :uba AND status = 'EMPTY'
            """
        ),
        {"uba": uba_id},
    )
    entry_pending_n = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM operation.upbit_position_slot
            WHERE user_broker_account_id = :uba AND status = 'ENTRY_PENDING'
            """
        ),
        {"uba": uba_id},
    )

    # ENTRY_PENDING + terminal zero-fill 주문 고착
    entry_pending_stuck = session.scalar(
        text(
            """
            SELECT COUNT(*)
            FROM operation.upbit_position_slot s
            JOIN trading.trading_order o ON o.order_id = s.entry_order_id
            WHERE s.user_broker_account_id = :uba
              AND s.status = 'ENTRY_PENDING'
              AND o.broker_code = 'UPBIT'
              AND UPPER(o.status_code) IN (
                  'CANCELLED','CANCELED','FAILED','REJECTED','EXPIRED'
              )
              AND COALESCE(o.filled_quantity, 0) = 0
            """
        ),
        {"uba": uba_id},
    )

    entry_eval = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM operation.upbit_entry_signal_shadow
            WHERE user_broker_account_id = :uba AND observed_at >= :ws
              AND variant = 'E0'
            """
        ),
        {"uba": uba_id, "ws": window_start},
    )
    entry_pass = session.scalar(
        text(
            """
            SELECT COUNT(*) FROM operation.upbit_entry_signal_shadow
            WHERE user_broker_account_id = :uba AND observed_at >= :ws
              AND variant = 'E0'
              AND UPPER(COALESCE(baseline_decision,'')) = 'PASS'
              AND COALESCE(
                    (indicator_snapshot->>'emit_suppressed')::boolean,
                    false
                  ) = false
            """
        ),
        {"uba": uba_id, "ws": window_start},
    )
    top_block = session.execute(
        text(
            """
            SELECT baseline_block_reason, COUNT(*) AS cnt
            FROM operation.upbit_entry_signal_shadow
            WHERE user_broker_account_id = :uba AND observed_at >= :ws
              AND variant = 'E0'
              AND UPPER(COALESCE(baseline_decision,'')) = 'BLOCK'
            GROUP BY baseline_block_reason
            ORDER BY cnt DESC
            LIMIT 1
            """
        ),
        {"uba": uba_id, "ws": window_start},
    ).first()
    top_block_reason = str(top_block[0]) if top_block and top_block[0] else None

    from stock_platform.operation.upbit_opportunity_scanner.scheduler import (
        upbit_opportunity_scanner_scheduler,
    )

    sc = upbit_opportunity_scanner_scheduler.status()
    scanner_runs = int(sc.get("run_count") or 0)
    scanner_running = bool(sc.get("running") or sc.get("started"))

    stages = {
        "FEED": 0,
        "SCANNER": scanner_runs,
        "CANDIDATE": int(opp_n or 0),
        "ANALYSIS": int(analysis_n or 0),
        "SELECTION": int(sel_n or 0),
        "WAITING": int(waiting_n or 0),
        "ENTRY_EVALUATION": int(entry_eval or 0),
        "ENTRY_PASS": int(entry_pass or 0),
        "ENTRY_PENDING": int(entry_pending_n or 0),
        "ENTRY_PENDING_STUCK": int(entry_pending_stuck or 0),
        "ADMISSION": 0,
        "ORDER": int(buy_orders or 0),
        "FILL": int(buy_fills or 0),
    }

    first_zero = None
    reason: str | None = None
    reasons: list[str] = []

    feed_ok = str(ctrl.get("strategy_runtime") or "").upper() != "ERROR"
    if not feed_ok:
        first_zero = "FEED"
        reason = "FEED_UNHEALTHY"
        reasons.append(reason)
    elif int(entry_pending_stuck or 0) > 0:
        first_zero = "ENTRY_PENDING"
        reason = "ENTRY_PENDING_ZERO_FILL_STUCK"
        reasons.append(reason)
    elif stages["ENTRY_EVALUATION"] > 0 and stages["ENTRY_PASS"] == 0:
        # 평가 활동이 있으면 scanner off-process 오판보다 ENTRY_SIGNAL 우선
        first_zero = "ENTRY_SIGNAL"
        reason = top_block_reason or "NO_ENTRY_SIGNAL_PASS"
        reasons.append(reason)
    elif not scanner_running and stages["SCANNER"] == 0 and stages["SELECTION"] == 0:
        first_zero = "SCANNER"
        reason = "NO_SCANNER_ACTIVITY"
        reasons.append(reason)
    elif stages["CANDIDATE"] == 0 and stages["SELECTION"] == 0 and stages["ENTRY_EVALUATION"] == 0:
        first_zero = "CANDIDATE"
        reason = "NO_CANDIDATES"
        reasons.append(reason)
    elif stages["SELECTION"] == 0 and stages["WAITING"] == 0 and int(empty_n or 0) > 0:
        first_zero = "SELECTION"
        reason = "NO_SELECTION"
        reasons.append(reason)
    elif stages["WAITING"] == 0 and int(open_n or 0) == 0 and stages["ENTRY_PASS"] == 0:
        first_zero = "WAITING"
        reason = "NO_WAITING_OR_OPEN"
        reasons.append(reason)
    elif stages["ENTRY_PASS"] > 0 and stages["ORDER"] == 0:
        first_zero = "ORDER"
        reason = "ENTRY_PASS_WITHOUT_ORDER"
        reasons.append(reason)
    elif stages["ORDER"] > 0 and stages["FILL"] == 0:
        first_zero = "FILL"
        reason = "NO_FILLS"
        reasons.append(reason)
    elif stages["ORDER"] == 0:
        first_zero = "ORDER"
        reason = "NO_ORDERS"
        reasons.append(reason)

    return {
        "ok": True,
        "schema": "upbit_funnel_v2",
        "user_broker_account_id": uba_id,
        "window_minutes": window_minutes,
        "window_start": window_start.isoformat(),
        "as_of": now.isoformat(),
        "stages": stages,
        "first_zero_stage": first_zero,
        "first_zero_reason": reason,
        "reasons": reasons,
        "top_entry_block_reason": top_block_reason,
        "open_positions": int(open_n or 0),
        "empty_slots": int(empty_n or 0),
        "entry_pending_stuck": int(entry_pending_stuck or 0),
        "scanner_running": scanner_running,
    }
