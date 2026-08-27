"""KIWOOM REAL autotrading funnel observability + FIRST_ZERO_STAGE.

전략 semantics(Golden Cross)는 변경하지 않는다.
UPBIT opportunity scanner와 혼용하지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.trading.account_models import UserBrokerAccount


def _resolve_fixed_symbols(
    session: Session, *, user_broker_account_id: int
) -> list[str]:
    """Strategy FIXED deployment symbols (보통 034310 단일).

    strategy_id=None 로 호출하면 settings fallback 만 보고 UNIVERSE=0 오탐이
    나므로 ACTIVE account_strategy_link 를 먼저 조회한다.
    """

    from stock_platform.strategy_deployment.definition_entities import (
        AccountStrategyLinkEntity,
    )
    from stock_platform.trading.kiwoom_unattended_stack_restore import (
        _resolve_kiwoom_stack_feed_symbols,
    )

    try:
        uba_id = int(user_broker_account_id)
        link = session.scalar(
            select(AccountStrategyLinkEntity)
            .where(
                AccountStrategyLinkEntity.user_broker_account_id == uba_id,
                AccountStrategyLinkEntity.is_active.is_(True),
            )
            .limit(1)
        )
        strategy_id = int(link.strategy_id) if link is not None else None

        # runtime feed 가 이미 구독 중이면 SoT 보조
        try:
            from stock_platform.realtime.kiwoom_market_realtime_runtime import (
                kiwoom_market_realtime_runtime as kmr,
            )

            st = kmr.status()
            if (
                int(st.get("user_broker_account_id") or 0) == uba_id
                and bool(st.get("running"))
            ):
                client = st.get("client") or {}
                live_syms = [
                    str(s).strip().upper()
                    for s in (client.get("symbols") or [])
                    if str(s or "").strip()
                ]
                if live_syms:
                    return sorted(set(live_syms))
        except Exception:  # noqa: BLE001
            pass

        symbols = _resolve_kiwoom_stack_feed_symbols(
            session,
            user_broker_account_id=uba_id,
            strategy_id=strategy_id,
            symbols=None,
        )
        return [str(s).upper() for s in (symbols or []) if s]
    except Exception:  # noqa: BLE001
        return []


def build_kiwoom_funnel_snapshot(
    session: Session,
    *,
    user_broker_account_id: int,
) -> dict[str, Any]:
    """한 화면용 funnel counts + FIRST_ZERO_STAGE (READ)."""

    uba_id = int(user_broker_account_id)
    uba = session.get(UserBrokerAccount, uba_id)
    broker = str(getattr(uba, "broker_code", "") or "").upper() if uba else ""
    if broker != "KIWOOM":
        return {
            "ok": False,
            "reason": "NOT_KIWOOM_UBA",
            "user_broker_account_id": uba_id,
        }

    from stock_platform.broker.live_transition_service import (
        LiveTradingTransitionService,
    )
    from stock_platform.realtime.kiwoom_market_realtime_runtime import (
    kiwoom_market_realtime_runtime as kmr,
)
    from stock_platform.trading.kiwoom_trading_day_lifecycle import (
        KiwoomTradingDayLifecycleService,
    )
    from stock_platform.trading.live_session_expiry import aware_utc
    from stock_platform.trading.live_unattended_authorization_service import (
        LiveUnattendedAuthorizationService,
    )
    from stock_platform.trading.market_hours_authorization import (
        krx_market_hours_state,
    )
    from stock_platform.trading.upbit_24x7_control import combined_control_status

    now = datetime.now(timezone.utc)
    mh = krx_market_hours_state(session, now=now)
    symbols = _resolve_fixed_symbols(session, user_broker_account_id=uba_id)
    act = LiveTradingTransitionService(session).peek_active(
        broker_code="KIWOOM", user_broker_account_id=uba_id
    )
    unattended = LiveUnattendedAuthorizationService(session).status_dict(uba_id)
    ctrl = combined_control_status(session, user_broker_account_id=uba_id)
    feed = kmr.status()
    lifecycle = KiwoomTradingDayLifecycleService(session).status_dict(uba_id)

    live_on = bool(getattr(uba, "live_order_enabled", False))
    arm_exp = aware_utc(getattr(uba, "arm_expires_at", None))
    arm_on = bool(getattr(uba, "live_armed", False)) and (
        arm_exp is None or arm_exp > now
    )
    activation_active = act is not None
    runtime = str(ctrl.get("strategy_runtime") or "STOPPED").upper()
    feed_running = bool(feed.get("running"))
    feed_connected = bool(feed.get("connected"))

    # today order funnel
    from stock_platform.order.entities import TradingOrderEntity
    from zoneinfo import ZoneInfo

    kst = ZoneInfo("Asia/Seoul")
    day0 = datetime.now(kst).replace(hour=0, minute=0, second=0, microsecond=0)
    day0_utc = day0.astimezone(timezone.utc)
    orders = list(
        session.scalars(
            select(TradingOrderEntity).where(
                TradingOrderEntity.user_broker_account_id == uba_id,
                TradingOrderEntity.broker_code == "KIWOOM",
                TradingOrderEntity.created_at >= day0_utc,
            )
        )
    )
    buys = [o for o in orders if str(o.side_code).upper() == "BUY"]
    filled_buys = [o for o in buys if str(o.status_code).upper() == "FILLED"]
    submitted = [
        o
        for o in buys
        if str(o.status_code).upper()
        in {"ACCEPTED", "FILLED", "PARTIALLY_FILLED", "SUBMITTING"}
    ]

    # Signal semantics (documentation only — not changed)
    signal_semantics = {
        "ABOVE_NO_NEW_CROSS_MEANING": (
            "MA short>long already true without a new cross event this bar"
        ),
        "NEW_CROSS_REQUIRED": True,
        "STRATEGY_CHANGED": False,
        "entry_reason_code": "MA_GOLDEN_CROSS",
        "note": (
            "KIWOOM FIXED CROSS_EVENT: prev_s<=prev_l and short>long required; "
            "already-above does not emit BUY"
        ),
    }

    stages = {
        "MARKET_OPEN": bool(mh.get("in_regular_session")),
        "UNIVERSE": len(symbols),
        "SCANNED": len(symbols),  # FIXED universe = scanned set
        "CANDIDATE": len(symbols),
        "SIGNAL": 0,  # natural signal count not persisted as counter; 0 unless runtime emits
        "AI_ALLOW": None,  # not first gate for KIWOOM FIXED
        "RISK_PASS": None,
        "ORDER_INTENT": len(buys),
        "ORDER_CREATED": len(buys),
        "ORDER_SUBMITTED": len(submitted),
        "FILLED": len(filled_buys),
    }

    # FIRST_ZERO in pipeline order
    first_zero = None
    reasons: list[str] = []
    if not mh.get("is_trading_day") or mh.get("past_close") or mh.get(
        "before_open"
    ):
        if not mh.get("in_regular_session"):
            first_zero = "MARKET_CLOSED"
            reasons.append("NOT_IN_REGULAR_SESSION")
    if first_zero is None and not activation_active:
        first_zero = "ACTIVATION_INACTIVE"
        reasons.append("NO_ACTIVE_KIWOOM_ACTIVATION")
    if first_zero is None and not live_on:
        first_zero = "LIVE_OFF"
    if first_zero is None and not arm_on:
        first_zero = "ARM_OFF"
    if first_zero is None and not bool(unattended.get("entry_authorized")):
        # after close protective only is expected
        if mh.get("in_regular_session"):
            first_zero = "NO_ACTIVE_LEASE"
    if first_zero is None and (not feed_running or not feed_connected):
        if mh.get("in_regular_session"):
            first_zero = "FEED_DOWN"
    if first_zero is None and runtime != "RUNNING":
        if mh.get("in_regular_session"):
            first_zero = "RUNTIME_STOPPED"
    if first_zero is None and len(symbols) == 0:
        first_zero = "UNIVERSE_EMPTY"
    if first_zero is None and stages["FILLED"] == 0 and stages["ORDER_CREATED"] == 0:
        # ready path but no new golden cross today
        first_zero = "NO_GOLDEN_CROSS_SIGNAL"
        reasons.append("ABOVE_NO_NEW_CROSS_OR_NO_CROSS_EVENT")

    return {
        "ok": True,
        "schema": "kiwoom_funnel_v1",
        "user_broker_account_id": uba_id,
        "as_of": now.isoformat(),
        "market_hours": {
            "in_regular_session": mh.get("in_regular_session"),
            "is_trading_day": mh.get("is_trading_day"),
            "session_type": mh.get("session_type"),
            "reason_code": mh.get("reason_code"),
        },
        "universe": {
            "UNIVERSE_SOURCE": "STRATEGY_FIXED_DEPLOYMENT",
            "UNIVERSE_SYMBOL_COUNT": len(symbols),
            "symbols": symbols,
            "034310_ONLY": symbols == ["034310"]
            or (len(symbols) == 1 and symbols[0] == "034310"),
        },
        "feed": {
            "REAL_FEED_SOURCE": "KIWOOM_MARKET_REALTIME",
            "running": feed_running,
            "connected": feed_connected,
            "REAL_TICK_SYMBOL_COUNT": len(feed.get("symbols") or symbols or []),
            "MOCK_DATA_USED_FOR_REAL_DECISION": bool(
                feed.get("kiwoom_market_data_use_mock")
            )
            if feed.get("kiwoom_market_data_use_mock") is not None
            else False,
            "execution_process_kiwoom_use_mock": feed.get(
                "execution_process_kiwoom_use_mock"
            ),
            "note": (
                "execution_process_kiwoom_use_mock alone does not imply "
                "MOCK decisions; market_data_use_mock blocks require_real"
            ),
        },
        "lifecycle": {
            "live": live_on,
            "arm": arm_on,
            "activation_active": activation_active,
            "runtime": runtime,
            "unattended_entry_authorized": unattended.get("entry_authorized"),
            "lifecycle_phase": (lifecycle or {}).get("phase")
            if isinstance(lifecycle, dict)
            else None,
            "next_trading_day_auto_start": unattended.get(
                "next_trading_day_auto_start"
            ),
        },
        "signal_semantics": signal_semantics,
        "funnel": stages,
        "FIRST_ZERO_STAGE": first_zero,
        "FIRST_ZERO_REASONS": reasons,
        "NEXT_SESSION_READINESS_HINT": {
            "requires": [
                "ACTIVE_KIWOOM_ACTIVATION",
                "LIVE_ON",
                "ARM_ON",
                "MARKET_HOURS_LEASE",
                "FEED_CONNECTED",
                "RUNTIME_RUNNING",
                "NEW_MA_GOLDEN_CROSS",
            ],
            "gates_not_bypassed": True,
        },
    }
