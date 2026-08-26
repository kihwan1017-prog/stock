"""UPBIT REAL autotrading funnel + FIRST_ZERO_STAGE (READ)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_platform.trading.account_models import UserBrokerAccount

UPBIT_FUNNEL_STAGES = (
    "FEED",
    "SCANNER",
    "CANDIDATE",
    "ANALYSIS",
    "SELECTION",
    "WAITING",
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

    # counts in window
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

    from stock_platform.operation.upbit_opportunity_scanner.scheduler import (
        upbit_opportunity_scanner_scheduler,
    )

    sc = upbit_opportunity_scanner_scheduler.status()
    scanner_runs = int(sc.get("run_count") or 0)

    stages = {
        "FEED": 0,
        "SCANNER": scanner_runs,
        "CANDIDATE": int(opp_n or 0),
        "ANALYSIS": int(analysis_n or 0),
        "SELECTION": int(sel_n or 0),
        "WAITING": int(waiting_n or 0),
        "ADMISSION": 0,
        "ORDER": int(buy_orders or 0),
        "FILL": int(buy_fills or 0),
    }

    first_zero = None
    reason: str | None = None

    feed_ok = str(ctrl.get("strategy_runtime") or "").upper() != "ERROR"
    if not feed_ok:
        first_zero = "FEED"
        reason = "FEED_UNHEALTHY"
    elif stages["SCANNER"] == 0 and stages["SELECTION"] == 0:
        first_zero = "SCANNER"
        reason = "NO_SCANNER_ACTIVITY"
    elif stages["CANDIDATE"] == 0 and stages["SELECTION"] == 0:
        first_zero = "CANDIDATE"
        reason = "NO_CANDIDATES"
    elif stages["SELECTION"] == 0:
        first_zero = "SELECTION"
        reason = "NO_SELECTION"
    elif stages["WAITING"] == 0 and int(open_n or 0) == 0:
        first_zero = "WAITING"
        reason = "NO_WAITING_OR_OPEN"
    elif stages["ORDER"] == 0:
        first_zero = "ORDER"
        reason = "NO_ORDERS"
    elif stages["FILL"] == 0:
        first_zero = "FILL"
        reason = "NO_FILLS"

    return {
        "ok": True,
        "schema": "upbit_funnel_v1",
        "user_broker_account_id": uba_id,
        "window_minutes": window_minutes,
        "window_start": window_start.isoformat(),
        "as_of": now.isoformat(),
        "stages": stages,
        "first_zero_stage": first_zero,
        "first_zero_reason": reason,
        "open_positions": int(open_n or 0),
    }
