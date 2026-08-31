"""Admin/API observability — KIWOOM multi-symbol universe."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
    CROSS_STATE_FRESH_CROSS,
    SHORT_MA_WINDOW,
    LONG_MA_WINDOW,
    SOURCE_MULTI_SYMBOL_V1,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.entities import (
    KiwoomMultiSymbolCrossStateEntity,
    KiwoomMultiSymbolMonitorEntity,
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

    monitor_rows = list(
        session.scalars(
            select(KiwoomMultiSymbolMonitorEntity)
            .where(
                KiwoomMultiSymbolMonitorEntity.user_broker_account_id == uba_id
            )
            .order_by(KiwoomMultiSymbolMonitorEntity.rank.asc())
        )
    )

    universe_count = session.scalar(
        select(func.count())
        .select_from(KiwoomMultiSymbolMonitorEntity)
        .where(KiwoomMultiSymbolMonitorEntity.user_broker_account_id == uba_id)
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
    signal_n = session.scalar(
        select(func.count())
        .select_from(KiwoomEntrySignalShadowEntity)
        .where(
            KiwoomEntrySignalShadowEntity.user_broker_account_id == uba_id,
            KiwoomEntrySignalShadowEntity.source == SOURCE_MULTI_SYMBOL_V1,
        )
    )

    return {
        "ok": True,
        "as_of": now.isoformat(),
        "user_broker_account_id": uba_id,
        "mode": "SHADOW_ONLY",
        "REAL_MULTI_SYMBOL_ENABLED": False,
        "universe": {
            "monitored_count": len(monitor_rows),
            "monitor_target": len(monitor_rows),
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
            "shadow_signals_total": int(signal_n or 0),
        },
        "why_no_trade_summary": _why_no_trade_summary(monitor_rows),
    }


def build_multi_symbol_funnel(
    session: Session,
    *,
    user_broker_account_id: int,
    prefilter_count: int | None = None,
    universe_count: int | None = None,
) -> dict[str, Any]:
    uba_id = int(user_broker_account_id)
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
    return {
        "UNIVERSE": universe_count,
        "PREFILTER": prefilter_count,
        "MONITORED": len(monitor_rows),
        "GOLDEN_CROSS": len(fresh),
        "SIGNAL": int(shadow_signals or 0),
        "RISK_PASS": 0,
        "ORDER_INTENT": 0,
        "FILLED": 0,
        "note": "SHADOW_ONLY — ORDER_INTENT/FILLED always 0 until user promotes REAL",
    }


def _why_no_trade_summary(
    rows: list[KiwoomMultiSymbolMonitorEntity],
) -> dict[str, Any]:
    if not rows:
        return {
            "user_friendly": "다종목 SHADOW 감시 roster가 아직 비어 있습니다.",
            "blockers": ["NO_MONITOR_ROSTER"],
        }
    fresh = sum(1 for r in rows if r.cross_state == CROSS_STATE_FRESH_CROSS)
    if fresh == 0:
        return {
            "user_friendly": (
                f"감시 {len(rows)}종목 중 Fresh Golden Cross 0건 — "
                "대부분 이미 SMA5>SMA20 상태이거나 교차 이벤트 없음."
            ),
            "blockers": ["NO_FRESH_GOLDEN_CROSS"],
            "monitored": len(rows),
            "golden_cross": 0,
            "signal": 0,
        }
    return {
        "user_friendly": (
            f"감시 {len(rows)}종목 · Fresh Golden Cross {fresh}건 (SHADOW 기록만, REAL 주문 없음)."
        ),
        "monitored": len(rows),
        "golden_cross": fresh,
    }
