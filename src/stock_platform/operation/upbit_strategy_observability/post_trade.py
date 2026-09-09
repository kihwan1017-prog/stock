# -*- coding: utf-8 -*-
"""Post-trade analytics from candle DB — ANALYTICS ONLY / LOOK-AHEAD.

FORBIDDEN: import from entry admission, MA evaluator, order executor, live safety.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_strategy_observability.constants import (
    POST_EXIT_HORIZONS_M,
    RULE_VERSION,
)
from stock_platform.operation.upbit_strategy_observability.entities import (
    UpbitStrategyObsPostTradeEntity,
)

logger = logging.getLogger(__name__)

# Explicit module marker for static tests
LOOKAHEAD_ANALYTICS_ONLY = True
MUST_NOT_DRIVE_TRADING = True


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def compute_mfe_mae_from_candles(
    session: Session,
    *,
    symbol: str,
    buy_at: datetime,
    sell_at: datetime,
    buy_price: float,
) -> dict[str, Any]:
    if buy_price <= 0:
        return {
            "mfe_pct": None,
            "mae_pct": None,
            "time_to_mfe_seconds": None,
            "time_to_mae_seconds": None,
        }
    buy_u = buy_at if buy_at.tzinfo else buy_at.replace(tzinfo=timezone.utc)
    sell_u = sell_at if sell_at.tzinfo else sell_at.replace(tzinfo=timezone.utc)
    rows = session.execute(
        text(
            """
            SELECT c.candle_at, c.high_price::float8, c.low_price::float8
            FROM market.candle_minute c
            JOIN market.instrument i ON i.instrument_id = c.instrument_id
            WHERE i.exchange_code='UPBIT' AND i.symbol=:sym AND c.timeframe=1
              AND c.candle_at >= :s AND c.candle_at <= :e
            ORDER BY c.candle_at
            """
        ),
        {"sym": symbol.upper(), "s": buy_u, "e": sell_u},
    ).all()
    mfe = mae = None
    t_mfe = t_mae = None
    for ca, high, low in rows:
        if ca.tzinfo is None:
            ca = ca.replace(tzinfo=timezone.utc)
        fav = (float(high) / buy_price - 1.0) * 100.0
        adv = (float(low) / buy_price - 1.0) * 100.0
        if mfe is None or fav > mfe:
            mfe = fav
            t_mfe = int((ca - buy_u).total_seconds())
        if mae is None or adv < mae:
            mae = adv
            t_mae = int((ca - buy_u).total_seconds())
    return {
        "mfe_pct": round(mfe, 8) if mfe is not None else None,
        "mae_pct": round(mae, 8) if mae is not None else None,
        "time_to_mfe_seconds": t_mfe,
        "time_to_mae_seconds": t_mae,
    }


def compute_post_exit_path(
    session: Session,
    *,
    symbol: str,
    sell_at: datetime,
    sell_price: float,
) -> dict[str, Any]:
    if sell_price <= 0:
        return {}
    sell_u = sell_at if sell_at.tzinfo else sell_at.replace(tzinfo=timezone.utc)
    end = sell_u + timedelta(minutes=max(POST_EXIT_HORIZONS_M))
    rows = session.execute(
        text(
            """
            SELECT c.candle_at, c.close_price::float8, c.high_price::float8
            FROM market.candle_minute c
            JOIN market.instrument i ON i.instrument_id = c.instrument_id
            WHERE i.exchange_code='UPBIT' AND i.symbol=:sym AND c.timeframe=1
              AND c.candle_at >= :s AND c.candle_at <= :e
            ORDER BY c.candle_at
            """
        ),
        {"sym": symbol.upper(), "s": sell_u, "e": end},
    ).all()
    by_min: dict[int, tuple[float, float]] = {}
    for ca, close, high in rows:
        if ca.tzinfo is None:
            ca = ca.replace(tzinfo=timezone.utc)
        mins = int((ca - sell_u).total_seconds() // 60)
        by_min[mins] = (float(close), float(high))
    out: dict[str, Any] = {"points": {}}
    for h in POST_EXIT_HORIZONS_M:
        # nearest available minute
        best = None
        best_d = None
        for m, (close, high) in by_min.items():
            d = abs(m - h)
            if best_d is None or d < best_d:
                best_d = d
                best = (close, high, m)
        if best is None:
            out["points"][f"+{h}m"] = None
            continue
        close, high, m = best
        out["points"][f"+{h}m"] = {
            "price": close,
            "return_vs_sell_pct": round((close / sell_price - 1.0) * 100.0, 8),
            "offset_min": m - h,
        }
    # max return horizons
    for h in (15, 30, 60):
        mx = None
        for m, (_c, high) in by_min.items():
            if 0 <= m <= h:
                r = (high / sell_price - 1.0) * 100.0
                if mx is None or r > mx:
                    mx = r
        out[f"post_exit_max_return_{h}m"] = round(mx, 8) if mx is not None else None
    out["lookahead_forbidden_for_trading"] = True
    return out


def compute_post_trade_analytics_safe(
    *,
    binding_id: int,
    user_broker_account_id: int,
    strategy_id: int | None,
    symbol: str,
    opened_at: datetime | None,
    closed_at: datetime | None,
    entry_price: Decimal | float | None,
    exit_price: Decimal | float | None,
) -> dict[str, Any]:
    """Own session write — never raises into trading."""

    from stock_platform.database.session import get_session_factory

    session = get_session_factory()()
    try:
        if not opened_at or not closed_at or entry_price is None:
            return {"ok": False, "reason": "INCOMPLETE_TRADE"}
        buy_px = float(entry_price)
        sell_px = float(exit_price) if exit_price is not None else buy_px
        mm = compute_mfe_mae_from_candles(
            session,
            symbol=symbol,
            buy_at=opened_at,
            sell_at=closed_at,
            buy_price=buy_px,
        )
        post = compute_post_exit_path(
            session, symbol=symbol, sell_at=closed_at, sell_price=sell_px
        )
        existing = session.scalar(
            select(UpbitStrategyObsPostTradeEntity).where(
                UpbitStrategyObsPostTradeEntity.binding_id == int(binding_id)
            )
        )
        if existing is None:
            existing = UpbitStrategyObsPostTradeEntity(
                binding_id=int(binding_id),
                user_broker_account_id=int(user_broker_account_id),
                strategy_id=int(strategy_id) if strategy_id else None,
                symbol=str(symbol).upper(),
                rule_version=RULE_VERSION,
                lookahead_forbidden_for_trading=True,
                note="ANALYTICS_ONLY_LOOKAHEAD_FORBIDDEN_FOR_TRADING",
            )
            session.add(existing)
        existing.opened_at = opened_at
        existing.closed_at = closed_at
        existing.entry_price = Decimal(str(buy_px))
        existing.exit_price = Decimal(str(sell_px))
        existing.mfe_pct = (
            Decimal(str(mm["mfe_pct"])) if mm.get("mfe_pct") is not None else None
        )
        existing.mae_pct = (
            Decimal(str(mm["mae_pct"])) if mm.get("mae_pct") is not None else None
        )
        existing.time_to_mfe_seconds = mm.get("time_to_mfe_seconds")
        existing.time_to_mae_seconds = mm.get("time_to_mae_seconds")
        existing.post_exit_json = post
        existing.analytics_json = {
            "source": "market.candle_minute",
            "lookahead_forbidden_for_trading": True,
        }
        session.commit()
        return {"ok": True, "binding_id": int(binding_id), **mm}
    except Exception as exc:  # noqa: BLE001
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning(
            "OBSERVABILITY_WRITE_FAILED",
            extra={"code": "POST_TRADE", "error": type(exc).__name__},
        )
        return {"ok": False, "code": "OBSERVABILITY_WRITE_FAILED", "error": type(exc).__name__}
    finally:
        session.close()


def compute_candidate_forward_returns_safe(
    session: Session,
    *,
    symbol: str,
    selected_at: datetime,
) -> dict[str, Any]:
    """Forward returns for counterfactual — ANALYTICS ONLY."""

    from stock_platform.operation.upbit_strategy_observability.constants import (
        FORWARD_HORIZONS_M,
    )

    sel = selected_at if selected_at.tzinfo else selected_at.replace(tzinfo=timezone.utc)
    end = sel + timedelta(minutes=max(FORWARD_HORIZONS_M))
    rows = session.execute(
        text(
            """
            SELECT c.candle_at, c.close_price::float8
            FROM market.candle_minute c
            JOIN market.instrument i ON i.instrument_id = c.instrument_id
            WHERE i.exchange_code='UPBIT' AND i.symbol=:sym AND c.timeframe=1
              AND c.candle_at >= :s AND c.candle_at <= :e
            ORDER BY c.candle_at
            """
        ),
        {"sym": symbol.upper(), "s": sel - timedelta(minutes=1), "e": end},
    ).all()
    base = None
    series: list[tuple[datetime, float]] = []
    for ca, close in rows:
        if ca.tzinfo is None:
            ca = ca.replace(tzinfo=timezone.utc)
        series.append((ca, float(close)))
        if base is None and ca >= sel - timedelta(seconds=90):
            base = float(close)
    out: dict[str, Any] = {
        "lookahead_forbidden_for_trading": True,
        "base_price": base,
    }
    if base is None or base <= 0:
        return out
    for h in FORWARD_HORIZONS_M:
        target = sel + timedelta(minutes=h)
        best = None
        best_d = None
        for ca, px in series:
            d = abs((ca - target).total_seconds())
            if best_d is None or d < best_d:
                best_d = d
                best = px
        out[f"fwd_{h}m_pct"] = (
            round((best / base - 1.0) * 100.0, 8) if best is not None else None
        )
    return out
