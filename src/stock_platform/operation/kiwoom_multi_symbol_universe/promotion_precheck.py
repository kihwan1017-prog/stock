"""REAL promotion precheck — unsafe 시 승격 STOP."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def evaluate_kiwoom_real_promotion_precheck(
    session: Session,
    *,
    user_broker_account_id: int,
    ops_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """authenticated ops-status + DB safety gate."""

    uba_id = int(user_broker_account_id)
    blockers: list[str] = []
    ops = ops_status or {}

    live = str(ops.get("live") or "").upper()
    arm = str(ops.get("arm") or "").upper()
    lease = (ops.get("unattended") or {}).get("entry_lease_active")
    stack = (ops.get("runtime_stack") or {}).get("label") or ""
    feed = (ops.get("market_feed") or {}).get("status") or ""
    ready = (ops.get("reliability") or {}).get("auto_trading_ready")

    if live != "ON":
        blockers.append("LIVE_OFF")
    if arm != "ON":
        blockers.append("ARM_OFF")
    if lease is not True:
        blockers.append("LEASE_INACTIVE")
    if stack != "4/4 RUNNING":
        blockers.append("STACK_INCOMPLETE")
    if str(feed).upper() not in {"REAL_FRESH", "FRESH", "CONNECTED", "OK"}:
        blockers.append("FEED_NOT_FRESH")
    if ready is not True:
        blockers.append("NOT_READY")

    try:
        from stock_platform.risk_engine.kill_switch_service import KillSwitchService

        if KillSwitchService(session).is_active():
            blockers.append("KILL_SWITCH_ACTIVE")
    except Exception:  # noqa: BLE001
        pass

    try:
        from stock_platform.trading.account_models import UserBrokerAccount

        uba = session.get(UserBrokerAccount, uba_id)
        if uba is not None and bool(getattr(uba, "trading_paused", False)):
            blockers.append("TRADING_PAUSED")
        if uba is not None and bool(getattr(uba, "is_paused", False)):
            blockers.append("ACCOUNT_PAUSED")
    except Exception:  # noqa: BLE001
        pass

    try:
        from stock_platform.order.entities import TradingOrderEntity
        from sqlalchemy import func, select

        ambiguous = session.scalar(
            select(func.count())
            .select_from(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id == uba_id,
                TradingOrderEntity.broker_code == "KIWOOM",
                TradingOrderEntity.status_code.in_(
                    ("REMOTE_LOOKUP_PENDING", "UNKNOWN", "AMBIGUOUS")
                ),
            )
        )
        if int(ambiguous or 0) > 0:
            blockers.append("AMBIGUOUS_ORDERS")
    except Exception:  # noqa: BLE001
        pass

    try:
        from stock_platform.order.entities import TradingOrderEntity
        from sqlalchemy import func, select

        open_real = session.scalar(
            select(func.count())
            .select_from(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id == uba_id,
                TradingOrderEntity.broker_code == "KIWOOM",
                TradingOrderEntity.status_code.in_(
                    (
                        "PENDING",
                        "SUBMITTING",
                        "SENT",
                        "CREATED",
                        "ACCEPTED",
                        "PARTIALLY_FILLED",
                    )
                ),
            )
        )
        if int(open_real or 0) > 0:
            blockers.append("OPEN_REAL_ORDERS")
    except Exception:  # noqa: BLE001
        pass

    return {
        "safe": len(blockers) == 0,
        "blockers": blockers,
        "ops_snapshot": {
            "live": live,
            "arm": arm,
            "lease": lease,
            "stack": stack,
            "feed": feed,
            "ready": ready,
        },
    }
