"""Admin/API observability — KIWOOM multi-symbol universe (SHADOW + REAL)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
    CROSS_STATE_FRESH_CROSS,
    SHORT_MA_WINDOW,
    LONG_MA_WINDOW,
    SOURCE_MULTI_SYMBOL_V1,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.entities import (
    KiwoomMultiSymbolMonitorEntity,
    KiwoomMultiSymbolRealSignalEntity,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.mode import (
    is_kiwoom_multi_symbol_real_enabled,
    is_kiwoom_multi_symbol_shadow_observability_enabled,
    resolve_kiwoom_multi_symbol_mode,
)
from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.entities import (
    KiwoomEntrySignalShadowEntity,
)
from stock_platform.realtime.kiwoom_market_realtime_runtime import (
    kiwoom_market_realtime_runtime,
)


def build_multi_symbol_status(
    session: Session,
    *,
    user_broker_account_id: int,
) -> dict[str, Any]:
    uba_id = int(user_broker_account_id)
    now = datetime.now(timezone.utc)
    settings = get_settings()
    mode = resolve_kiwoom_multi_symbol_mode(settings)
    real_enabled = is_kiwoom_multi_symbol_real_enabled(settings)

    monitor_rows = list(
        session.scalars(
            select(KiwoomMultiSymbolMonitorEntity)
            .where(
                KiwoomMultiSymbolMonitorEntity.user_broker_account_id == uba_id
            )
            .order_by(KiwoomMultiSymbolMonitorEntity.rank.asc())
        )
    )

    feed = kiwoom_market_realtime_runtime.status()
    client = feed.get("client") or {}
    subscribed = [
        str(s).upper()
        for s in (client.get("symbols") or [])
        if str(s or "").strip()
    ]

    top10 = [
        {
            "rank": r.rank,
            "symbol": r.symbol,
            "name": r.name,
            "price": str(r.price) if r.price is not None else None,
            "volume": str(r.volume) if r.volume is not None else None,
            "trading_value": str(r.trading_value) if r.trading_value is not None else None,
            "change_pct": str(r.change_pct) if r.change_pct is not None else None,
            "sma5": str(r.sma5) if r.sma5 is not None else None,
            "sma20": str(r.sma20) if r.sma20 is not None else None,
            "cross_state": r.cross_state,
            "block_reason": r.block_reason,
            "signal_status": r.signal_status,
            "selected_at": r.selected_at.isoformat() if r.selected_at else None,
        }
        for r in monitor_rows
    ]

    fresh_n = sum(
        1 for r in monitor_rows if r.cross_state == CROSS_STATE_FRESH_CROSS
    )
    shadow_n = session.scalar(
        select(func.count())
        .select_from(KiwoomEntrySignalShadowEntity)
        .where(
            KiwoomEntrySignalShadowEntity.user_broker_account_id == uba_id,
            KiwoomEntrySignalShadowEntity.source == SOURCE_MULTI_SYMBOL_V1,
        )
    )
    real_n = session.scalar(
        select(func.count())
        .select_from(KiwoomMultiSymbolRealSignalEntity)
        .where(
            KiwoomMultiSymbolRealSignalEntity.user_broker_account_id == uba_id,
        )
    )
    duplicate_blocked = session.scalar(
        select(func.count())
        .select_from(KiwoomMultiSymbolRealSignalEntity)
        .where(
            KiwoomMultiSymbolRealSignalEntity.user_broker_account_id == uba_id,
            KiwoomMultiSymbolRealSignalEntity.dispatch_state.in_(
                ("DUPLICATE_REAL_SIGNAL", "DUPLICATE_FINGERPRINT")
            ),
        )
    )

    monitor_target = int(
        getattr(settings, "kiwoom_multi_symbol_monitor_target", 10) or 10
    )

    return {
        "ok": True,
        "as_of": now.isoformat(),
        "user_broker_account_id": uba_id,
        "mode": mode,
        "MULTI_SYMBOL_MODE": mode,
        "REAL_MULTI_SYMBOL_ENABLED": real_enabled,
        "MULTI_SYMBOL_REAL_ENABLED": real_enabled,
        "MULTI_SYMBOL_SHADOW_OBSERVABILITY_ENABLED": (
            is_kiwoom_multi_symbol_shadow_observability_enabled(settings)
            or bool(getattr(settings, "kiwoom_multi_symbol_shadow_enabled", False))
        ),
        "DUPLICATE_REAL_SIGNAL_PROTECTED": True,
        "universe": {
            "monitored_count": len(monitor_rows),
            "monitor_target": monitor_target,
        },
        "top10": top10,
        "feed": {
            "physical_socket_count": 1 if feed.get("running") else 0,
            "subscribed_symbol_count": len(subscribed),
            "subscribed_symbols": subscribed,
            "connected": feed.get("connected"),
            "running": feed.get("running"),
        },
        "golden_cross_policy": {
            "policy": "FRESH_CROSS_EVENT_REQUIRED",
            "short_ma": SHORT_MA_WINDOW,
            "long_ma": LONG_MA_WINDOW,
        },
        "counts": {
            "fresh_cross_monitored": fresh_n,
            "shadow_signals_total": int(shadow_n or 0),
            "real_signals_total": int(real_n or 0),
            "duplicate_real_blocked": int(duplicate_blocked or 0),
        },
        "why_no_trade_summary": _why_no_trade_summary(monitor_rows, real_enabled),
        "KIWOOM_MULTI_SYMBOL_REAL_READY": _real_ready(
            monitor_rows, real_enabled, feed, monitor_target
        ),
    }


def build_multi_symbol_funnel(
    session: Session,
    *,
    user_broker_account_id: int,
    prefilter_count: int | None = None,
    universe_count: int | None = None,
) -> dict[str, Any]:
    uba_id = int(user_broker_account_id)
    real_enabled = is_kiwoom_multi_symbol_real_enabled()
    monitor_rows = list(
        session.scalars(
            select(KiwoomMultiSymbolMonitorEntity).where(
                KiwoomMultiSymbolMonitorEntity.user_broker_account_id == uba_id
            )
        )
    )
    fresh = [
        r for r in monitor_rows if r.cross_state == CROSS_STATE_FRESH_CROSS
    ]
    shadow_signals = session.scalar(
        select(func.count())
        .select_from(KiwoomEntrySignalShadowEntity)
        .where(
            KiwoomEntrySignalShadowEntity.user_broker_account_id == uba_id,
            KiwoomEntrySignalShadowEntity.source == SOURCE_MULTI_SYMBOL_V1,
        )
    )
    real_signals = session.scalar(
        select(func.count())
        .select_from(KiwoomMultiSymbolRealSignalEntity)
        .where(
            KiwoomMultiSymbolRealSignalEntity.user_broker_account_id == uba_id,
        )
    )
    published_real = session.scalar(
        select(func.count())
        .select_from(KiwoomMultiSymbolRealSignalEntity)
        .where(
            KiwoomMultiSymbolRealSignalEntity.user_broker_account_id == uba_id,
            KiwoomMultiSymbolRealSignalEntity.dispatch_state == "PUBLISHED",
        )
    )
    funnel = {
        "UNIVERSE": universe_count,
        "PREFILTER": prefilter_count,
        "MONITORED": len(monitor_rows),
        "FRESH_GOLDEN_CROSS": len(fresh),
        "SHADOW_SIGNAL": int(shadow_signals or 0),
        "REAL_SIGNAL": int(real_signals or 0),
        "EXECUTOR_RECEIVED": int(published_real or 0),
        "RISK_PASS": 0,
        "ORDER_INTENT": 0,
        "BROKER_SUBMITTED": 0,
        "FILLED": 0,
        "mode": resolve_kiwoom_multi_symbol_mode(),
    }
    if not real_enabled:
        funnel["note"] = "SHADOW mode — REAL funnel stages remain 0 until promotion"
    return funnel


def _real_ready(
    rows: list[KiwoomMultiSymbolMonitorEntity],
    real_enabled: bool,
    feed: dict[str, Any],
    monitor_target: int,
) -> bool:
    if not real_enabled:
        return False
    if len(rows) != monitor_target:
        return False
    if not feed.get("running") or not feed.get("connected"):
        return False
    return True


def _why_no_trade_summary(
    rows: list[KiwoomMultiSymbolMonitorEntity],
    real_enabled: bool,
) -> dict[str, Any]:
    if not rows:
        return {
            "user_friendly": "다종목 roster가 아직 비어 있습니다.",
            "blockers": ["NO_MONITOR_ROSTER"],
        }
    fresh = sum(1 for r in rows if r.cross_state == CROSS_STATE_FRESH_CROSS)
    per_symbol = {
        r.symbol: r.block_reason or "NO_FRESH_GOLDEN_CROSS" for r in rows
    }
    if fresh == 0:
        return {
            "user_friendly": (
                f"감시 {len(rows)}종목 중 Fresh Golden Cross 0건 — "
                "대부분 ABOVE_NO_NEW_CROSS 또는 history 부족."
            ),
            "blockers": ["NO_FRESH_GOLDEN_CROSS"],
            "monitored": len(rows),
            "golden_cross": 0,
            "per_symbol_blockers": per_symbol,
        }
    channel = "REAL+SHADOW" if real_enabled else "SHADOW only"
    return {
        "user_friendly": (
            f"감시 {len(rows)}종목 · Fresh Golden Cross {fresh}건 ({channel})."
        ),
        "monitored": len(rows),
        "golden_cross": fresh,
        "per_symbol_blockers": per_symbol,
    }
