"""KIWOOM market feed STALE self-heal — hard reconnect + REAL tick verify.

주문 mutation 없음. connected=true 만으로 복구 성공 처리 금지.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from sqlalchemy.orm import Session

from stock_platform.trading.autotrading_health_service import (
    build_trading_health_snapshot,
)
from stock_platform.trading.autotrading_health_slo import (
    AutotradingHealthSlo,
    load_autotrading_health_slo,
)

logger = structlog.get_logger(__name__)

_FEED_FRESH = frozenset(
    {"REAL_FRESH", "FRESH", "CONNECTED", "HEALTHY", "OK"}
)


def kiwoom_runtime_feed_is_stale(
    runtime_status: dict[str, Any],
    *,
    slo: AutotradingHealthSlo | None = None,
) -> bool:
    """receive task 살아있어도 tick age 초과면 STALE (idempotent no-op 방지)."""

    slo = slo or load_autotrading_health_slo()
    running = bool(runtime_status.get("running"))
    if not running:
        return True

    connected = bool(runtime_status.get("connected"))
    age = runtime_status.get("feed_age_seconds")
    client = runtime_status.get("client") if isinstance(runtime_status.get("client"), dict) else {}
    reason = str((client or {}).get("reason") or runtime_status.get("reason") or "").upper()

    if reason in {"TICK_STALE", "QUOTE_STALE", "FEED_NOT_RUNNING"}:
        return True
    if not connected:
        return True
    if age is None:
        # connected but never received tick during REGULAR — stale treat
        event_count = int((client or {}).get("event_count") or 0)
        return event_count <= 0
    try:
        return float(age) > float(slo.feed_max_age_seconds)
    except (TypeError, ValueError):
        return True


def kiwoom_health_feed_is_stale(
    health_snapshot: dict[str, Any],
    *,
    slo: AutotradingHealthSlo | None = None,
) -> bool:
    """health components/feed_detail 기준 STALE 판정."""

    slo = slo or load_autotrading_health_slo()
    feed_st = str((health_snapshot.get("components") or {}).get("feed") or "").upper()
    if feed_st in {"STALE", "DISCONNECTED", "DOWN", "UNHEALTHY"}:
        return True
    if feed_st in _FEED_FRESH:
        hb_age = (health_snapshot.get("heartbeats") or {}).get("feed_age_seconds")
        if hb_age is not None:
            try:
                return float(hb_age) > float(slo.feed_max_age_seconds)
            except (TypeError, ValueError):
                return True
        return False
    detail = health_snapshot.get("feed_detail") or {}
    if str(detail.get("reason") or "").upper() in {"TICK_STALE", "QUOTE_STALE"}:
        return True
    age = detail.get("age_seconds")
    if age is not None:
        try:
            return float(age) > float(slo.feed_max_age_seconds)
        except (TypeError, ValueError):
            return True
    return feed_st not in _FEED_FRESH and feed_st not in {"CONNECTING", "UNKNOWN", ""}


async def ensure_kiwoom_feed_fresh(
    session: Session,
    *,
    user_broker_account_id: int,
    symbols: list[str],
    actor: str,
    health_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """STALE이면 stop→start hard reconnect. fresh면 idempotent symbol merge."""

    from stock_platform.realtime.kiwoom_market_realtime_runtime import (
        kiwoom_market_realtime_runtime,
    )

    uba_id = int(user_broker_account_id)
    slo = load_autotrading_health_slo()
    snap = health_snapshot or build_trading_health_snapshot(
        session, user_broker_account_id=uba_id
    )
    st_before = kiwoom_market_realtime_runtime.status()
    client_before = (
        st_before.get("client") if isinstance(st_before.get("client"), dict) else {}
    )
    event_count_before = int((client_before or {}).get("event_count") or 0)

    stale = kiwoom_health_feed_is_stale(snap, slo=slo) or kiwoom_runtime_feed_is_stale(
        st_before, slo=slo
    )
    running = bool(st_before.get("running"))
    same_uba = int(st_before.get("user_broker_account_id") or 0) == uba_id

    result: dict[str, Any] = {
        "market": "KIWOOM",
        "user_broker_account_id": uba_id,
        "actor": actor,
        "stale_before": stale,
        "event_count_before": event_count_before,
        "hard_reconnect": False,
    }

    if stale and running and same_uba:
        logger.info(
            "kiwoom_feed_stale_hard_reconnect",
            uba_id=uba_id,
            actor=actor,
            feed_age=st_before.get("feed_age_seconds"),
            last_error=(client_before or {}).get("last_error"),
        )
        await kiwoom_market_realtime_runtime.stop()
        result["hard_reconnect"] = True
        running = False

    if not symbols:
        result.update({"started": False, "reason": "SYMBOLS_REQUIRED"})
        return result

    if running and same_uba and not stale:
        started = await kiwoom_market_realtime_runtime.start(
            user_broker_account_id=uba_id,
            symbols=symbols,
            require_real=True,
        )
        result.update(
            {
                "started": True,
                "idempotent": True,
                "reason": "ALREADY_FRESH",
                "connected": bool(started.get("connected")),
            }
        )
        return result

    started = await kiwoom_market_realtime_runtime.start(
        user_broker_account_id=uba_id,
        symbols=symbols,
        require_real=True,
    )
    result.update(
        {
            "started": bool(started.get("started")),
            "already_running": bool(started.get("already_running")),
            "connected": bool(started.get("connected")),
            "reason": started.get("reason"),
        }
    )
    return result


async def verify_kiwoom_feed_recovery(
    session: Session,
    *,
    user_broker_account_id: int,
    event_count_before: int = 0,
    wait_seconds: float = 8.0,
    poll_interval: float = 0.5,
) -> dict[str, Any]:
    """REAL tick + freshness 확인 — connected만으로 성공 금지."""

    from stock_platform.realtime.kiwoom_market_realtime_runtime import (
        kiwoom_market_realtime_runtime,
    )

    uba_id = int(user_broker_account_id)
    slo = load_autotrading_health_slo()
    deadline = time.monotonic() + max(1.0, float(wait_seconds))
    last: dict[str, Any] = {}

    while time.monotonic() < deadline:
        snap = build_trading_health_snapshot(session, user_broker_account_id=uba_id)
        st = kiwoom_market_realtime_runtime.status()
        client = st.get("client") if isinstance(st.get("client"), dict) else {}
        event_count = int((client or {}).get("event_count") or 0)
        feed_st = str((snap.get("components") or {}).get("feed") or "")
        age = snap.get("heartbeats", {}).get("feed_age_seconds")
        if age is None:
            age = st.get("feed_age_seconds")

        fresh_age = True
        if age is not None:
            try:
                fresh_age = float(age) <= float(slo.feed_max_age_seconds)
            except (TypeError, ValueError):
                fresh_age = False

        tick_delta = event_count - int(event_count_before)
        real_tick = tick_delta > 0 or (
            event_count > 0 and feed_st == "REAL_FRESH" and fresh_age
        )
        verified = (
            feed_st == "REAL_FRESH"
            and bool(st.get("connected"))
            and bool(st.get("running"))
            and real_tick
            and fresh_age
        )
        last = {
            "verified": verified,
            "feed": feed_st,
            "connected": bool(st.get("connected")),
            "running": bool(st.get("running")),
            "event_count": event_count,
            "event_count_delta": tick_delta,
            "feed_age_seconds": age,
            "symbols": (client or {}).get("symbols"),
            "subscription_count": (client or {}).get("subscription_count"),
        }
        if verified:
            return last
        await asyncio.sleep(poll_interval)

    last["verified"] = False
    last["reason"] = "VERIFY_TIMEOUT"
    return last
