"""KIWOOM forward shadow — price lookup + outcome maturation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.constants import (
    HORIZON_MATURED,
    HORIZON_MISSING_DATA,
    HORIZON_PENDING,
    KIWOOM_24H_SEMANTICS,
    OUTCOME_WINDOWS_MIN,
)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:  # noqa: BLE001
        return None


def future_prices_kiwoom(
    session: Session,
    *,
    symbol: str,
    observed_at: datetime,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """KRX minute candle as-of outcome — look-ahead 금지."""

    obs = _as_utc(observed_at)
    assert obs is not None
    as_of = _as_utc(as_of) or datetime.now(timezone.utc)

    entry = session.scalar(
        text(
            """
            SELECT c.close_price
            FROM market.candle_minute c
            JOIN market.instrument i ON i.instrument_id = c.instrument_id
            WHERE i.symbol = :sym AND c.timeframe = 1
              AND c.candle_at <= :obs
            ORDER BY c.candle_at DESC
            LIMIT 1
            """
        ),
        {"sym": symbol, "obs": obs},
    )
    entry_px = _dec(entry)
    if entry_px is None or entry_px <= 0:
        return {"ok": False, "reason": "NO_ENTRY_PRICE"}

    futures: dict[str, Decimal | None] = {}
    horizons: dict[str, dict[str, Any]] = {}
    highs: list[Decimal] = []
    lows: list[Decimal] = []

    for mins in OUTCOME_WINDOWS_MIN:
        key = f"future_{mins}m"
        target = obs + timedelta(minutes=mins)
        if as_of < target:
            futures[key] = None
            horizons[key] = {"status": HORIZON_PENDING, "return_pct": None}
            continue
        row = session.execute(
            text(
                """
                SELECT c.close_price, c.high_price, c.low_price, c.candle_at
                FROM market.candle_minute c
                JOIN market.instrument i ON i.instrument_id = c.instrument_id
                WHERE i.symbol = :sym AND c.timeframe = 1
                  AND c.candle_at <= :tgt
                ORDER BY c.candle_at DESC
                LIMIT 1
                """
            ),
            {"sym": symbol, "tgt": target},
        ).mappings().first()
        if not row:
            futures[key] = None
            horizons[key] = {"status": HORIZON_MISSING_DATA, "return_pct": None}
            continue
        close = _dec(row["close_price"])
        if close is None:
            futures[key] = None
            horizons[key] = {"status": HORIZON_MISSING_DATA, "return_pct": None}
            continue
        ret = (close - entry_px) / entry_px * Decimal("100")
        futures[key] = ret
        horizons[key] = {
            "status": HORIZON_MATURED,
            "return_pct": float(ret),
        }
        span = session.execute(
            text(
                """
                SELECT c.high_price, c.low_price
                FROM market.candle_minute c
                JOIN market.instrument i ON i.instrument_id = c.instrument_id
                WHERE i.symbol = :sym AND c.timeframe = 1
                  AND c.candle_at >= :obs AND c.candle_at <= :tgt
                """
            ),
            {"sym": symbol, "obs": obs, "tgt": target},
        ).mappings().all()
        for r in span:
            h = _dec(r["high_price"])
            lo = _dec(r["low_price"])
            if h is not None:
                highs.append(h)
            if lo is not None:
                lows.append(lo)

    mfe = (max(highs) - entry_px) / entry_px * Decimal("100") if highs else None
    mae = (min(lows) - entry_px) / entry_px * Decimal("100") if lows else None
    fut15 = futures.get("future_15m")
    net15 = fut15 if fut15 is not None else None

    all_resolved = all(
        horizons.get(f"future_{m}m", {}).get("status")
        in (HORIZON_MATURED, HORIZON_MISSING_DATA)
        for m in OUTCOME_WINDOWS_MIN
    )

    return {
        "ok": True,
        "entry_reference_price": entry_px,
        "futures": {k: (float(v) if v is not None else None) for k, v in futures.items()},
        "horizons": horizons,
        "all_horizons_resolved": all_resolved,
        "mfe_pct": float(mfe) if mfe is not None else None,
        "mae_pct": float(mae) if mae is not None else None,
        "net_return_15m_pct": float(net15) if net15 is not None else None,
        "kiwoom_24h_semantics": KIWOOM_24H_SEMANTICS,
        "as_of": as_of.isoformat(),
    }
