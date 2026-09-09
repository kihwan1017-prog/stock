# -*- coding: utf-8 -*-
"""Candidate counterfactual forward returns — BACKGROUND / ANALYTICS ONLY.

LOOK-AHEAD: must never enter scanner, signal, admission, or order paths.
Uses market.candle_minute only (no broker polling).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_strategy_observability.constants import (
    CF_BATCH_LIMIT_SYMBOLS,
    DQ_AVAILABLE,
    DQ_PENDING_FUTURE_DATA,
    DQ_SOURCE_DATA_MISSING,
    FORWARD_HORIZONS_M,
    RULE_VERSION_V1_1,
)
from stock_platform.operation.upbit_strategy_observability.entities import (
    UpbitStrategyObsCounterfactualEntity,
)

logger = logging.getLogger(__name__)

LOOKAHEAD_ANALYTICS_ONLY = True
MUST_NOT_DRIVE_TRADING = True
NO_BROKER_API = True


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def compute_forward_horizons(
    session: Session,
    *,
    symbol: str,
    observed_at: datetime,
    now: datetime | None = None,
) -> dict[int, dict[str, Any]]:
    """Per-horizon forward return with explicit DQ status (never fake 0%)."""

    now_u = _aware(now or datetime.now(timezone.utc))
    obs = _aware(observed_at)
    end = obs + timedelta(minutes=max(FORWARD_HORIZONS_M) + 2)
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
        {
            "sym": symbol.upper(),
            "s": obs - timedelta(minutes=2),
            "e": end,
        },
    ).all()
    series: list[tuple[datetime, float]] = []
    for ca, close in rows:
        series.append((_aware(ca), float(close)))

    base = None
    for ca, px in series:
        if abs((ca - obs).total_seconds()) <= 90:
            base = px
            break
    if base is None and series:
        # nearest at-or-before observed
        before = [(ca, px) for ca, px in series if ca <= obs]
        if before:
            base = before[-1][1]

    out: dict[int, dict[str, Any]] = {}
    for h in FORWARD_HORIZONS_M:
        target = obs + timedelta(minutes=h)
        if now_u < target:
            out[h] = {
                "forward_return_pct": None,
                "base_price": base,
                "forward_price": None,
                "status": DQ_PENDING_FUTURE_DATA,
                "status_reason": "HORIZON_NOT_YET_REACHED",
            }
            continue
        if base is None or base <= 0:
            out[h] = {
                "forward_return_pct": None,
                "base_price": None,
                "forward_price": None,
                "status": DQ_SOURCE_DATA_MISSING,
                "status_reason": "BASE_PRICE_MISSING",
            }
            continue
        best = None
        best_d = None
        for ca, px in series:
            d = abs((ca - target).total_seconds())
            if d <= 120 and (best_d is None or d < best_d):
                best_d = d
                best = px
        if best is None:
            out[h] = {
                "forward_return_pct": None,
                "base_price": base,
                "forward_price": None,
                "status": DQ_SOURCE_DATA_MISSING,
                "status_reason": "FORWARD_CANDLE_MISSING",
            }
            continue
        out[h] = {
            "forward_return_pct": round((best / base - 1.0) * 100.0, 8),
            "base_price": base,
            "forward_price": best,
            "status": DQ_AVAILABLE,
            "status_reason": None,
        }
    return out


def _should_overwrite(existing_status: str | None, new_status: str) -> bool:
    """Idempotent: never downgrade AVAILABLE → PENDING; allow PENDING → AVAILABLE."""

    if existing_status == DQ_AVAILABLE and new_status != DQ_AVAILABLE:
        return False
    return True


def upsert_counterfactual_rows(
    session: Session,
    *,
    scanner_run_id: str,
    symbol: str,
    selected: bool,
    observed_at: datetime,
    horizons: dict[int, dict[str, Any]],
) -> int:
    """Duplicate-safe upsert. Returns number of rows written/updated."""

    now = datetime.now(timezone.utc)
    written = 0
    for h, payload in horizons.items():
        existing = session.scalar(
            select(UpbitStrategyObsCounterfactualEntity).where(
                UpbitStrategyObsCounterfactualEntity.scanner_run_id
                == str(scanner_run_id),
                UpbitStrategyObsCounterfactualEntity.symbol == symbol.upper(),
                UpbitStrategyObsCounterfactualEntity.horizon_m == int(h),
            )
        )
        new_status = str(payload["status"])
        if existing is not None and not _should_overwrite(
            existing.status, new_status
        ):
            continue

        row_vals = {
            "scanner_run_id": str(scanner_run_id),
            "symbol": symbol.upper(),
            "horizon_m": int(h),
            "forward_return_pct": (
                Decimal(str(payload["forward_return_pct"]))
                if payload.get("forward_return_pct") is not None
                else None
            ),
            "base_price": (
                Decimal(str(payload["base_price"]))
                if payload.get("base_price") is not None
                else None
            ),
            "forward_price": (
                Decimal(str(payload["forward_price"]))
                if payload.get("forward_price") is not None
                else None
            ),
            "status": new_status,
            "status_reason": payload.get("status_reason"),
            "selected": bool(selected),
            "observed_at": _aware(observed_at),
            "computed_at": (
                now
                if new_status == DQ_AVAILABLE
                else (existing.computed_at if existing is not None else None)
            ),
            "lookahead_forbidden_for_trading": True,
            "rule_version": RULE_VERSION_V1_1,
            "updated_at": now,
        }
        if existing is None:
            session.add(UpbitStrategyObsCounterfactualEntity(**row_vals, created_at=now))
        else:
            for k, v in row_vals.items():
                setattr(existing, k, v)
        written += 1
    return written


def process_counterfactual_batch(
    session: Session,
    *,
    limit_symbols: int = CF_BATCH_LIMIT_SYMBOLS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Mature pending counterfactuals for universe rows. Own caller commits."""

    now_u = _aware(now or datetime.now(timezone.utc))
    # Prefer rows old enough that at least 5m horizon may be ready
    cutoff = now_u - timedelta(minutes=5)
    # Skip symbols that already have all horizons AVAILABLE
    rows = list(
        session.execute(
            text(
                """
                SELECT u.scanner_run_id, u.symbol, u.selected, u.observed_at
                FROM operation.upbit_strategy_obs_scanner_universe u
                WHERE u.observed_at <= :cutoff
                  AND NOT EXISTS (
                    SELECT 1
                    FROM operation.upbit_strategy_obs_counterfactual c
                    WHERE c.scanner_run_id = u.scanner_run_id
                      AND c.symbol = u.symbol
                      AND c.horizon_m = 60
                      AND c.status = 'AVAILABLE'
                  )
                ORDER BY u.observed_at ASC
                LIMIT :lim
                """
            ),
            {"cutoff": cutoff, "lim": int(limit_symbols)},
        ).all()
    )
    processed = 0
    written = 0
    pending = 0
    available = 0
    missing = 0
    query_count = 1  # selection query
    for scanner_run_id, symbol, selected, observed_at in rows:
        horizons = compute_forward_horizons(
            session,
            symbol=str(symbol),
            observed_at=observed_at,
            now=now_u,
        )
        query_count += 1
        n = upsert_counterfactual_rows(
            session,
            scanner_run_id=str(scanner_run_id),
            symbol=str(symbol),
            selected=bool(selected),
            observed_at=observed_at,
            horizons=horizons,
        )
        written += n
        processed += 1
        for h, p in horizons.items():
            st = p["status"]
            if st == DQ_AVAILABLE:
                available += 1
            elif st == DQ_PENDING_FUTURE_DATA:
                pending += 1
            else:
                missing += 1
    return {
        "ok": True,
        "processed_symbols": processed,
        "rows_written": written,
        "available_horizons": available,
        "pending_horizons": pending,
        "missing_horizons": missing,
        "query_count": query_count,
        "batch_size": int(limit_symbols),
        "lookahead_forbidden_for_trading": True,
        "broker_api_calls": 0,
    }


def sync_selected_flags(session: Session, *, scanner_run_id: str) -> int:
    """Keep CF.selected aligned with universe.selected (no shrink)."""

    result = session.execute(
        text(
            """
            UPDATE operation.upbit_strategy_obs_counterfactual c
            SET selected = u.selected, updated_at = now()
            FROM operation.upbit_strategy_obs_scanner_universe u
            WHERE c.scanner_run_id = :run
              AND u.scanner_run_id = c.scanner_run_id
              AND u.symbol = c.symbol
              AND c.selected IS DISTINCT FROM u.selected
            """
        ),
        {"run": str(scanner_run_id)},
    )
    return int(result.rowcount or 0)
