"""Bulk market.price_daily loaders — N+1 제거."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
    MIN_COMPLETED_BARS,
)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def load_bulk_latest_two_daily_rows(
    session: Session,
    instrument_ids: list[int],
) -> dict[int, tuple[dict[str, Any], dict[str, Any] | None]]:
    """instrument_id → (latest_row, previous_row) — 단일 set-based query."""

    ids = [int(x) for x in instrument_ids if x]
    if not ids:
        return {}

    stmt = text(
        """
        WITH ranked AS (
            SELECT
                instrument_id,
                trade_date,
                close_price,
                volume,
                trade_value,
                change_rate,
                ROW_NUMBER() OVER (
                    PARTITION BY instrument_id
                    ORDER BY trade_date DESC
                ) AS rn
            FROM market.price_daily
            WHERE instrument_id IN :instrument_ids
        )
        SELECT
            instrument_id,
            trade_date,
            close_price,
            volume,
            trade_value,
            change_rate,
            rn
        FROM ranked
        WHERE rn <= 2
        ORDER BY instrument_id, rn
        """
    ).bindparams(bindparam("instrument_ids", expanding=True))

    rows = session.execute(stmt, {"instrument_ids": ids}).mappings().all()
    out: dict[int, tuple[dict[str, Any], dict[str, Any] | None]] = {}
    for row in rows:
        iid = int(row["instrument_id"])
        payload = dict(row)
        rn = int(payload.pop("rn"))
        if rn == 1:
            out[iid] = (payload, None)
        elif rn == 2 and iid in out:
            latest, _ = out[iid]
            out[iid] = (latest, payload)
    return out


def load_bulk_completed_closes(
    session: Session,
    instrument_ids: list[int],
    *,
    required: int = MIN_COMPLETED_BARS,
    today: date,
    extra_rows: int = 5,
) -> dict[int, list[Decimal]]:
    """여러 종목 completed daily close bulk load."""

    ids = [int(x) for x in instrument_ids if x]
    if not ids:
        return {}

    limit_per_symbol = max(required + extra_rows, required)
    stmt = text(
        """
        WITH ranked AS (
            SELECT
                instrument_id,
                trade_date,
                close_price,
                ROW_NUMBER() OVER (
                    PARTITION BY instrument_id
                    ORDER BY trade_date DESC
                ) AS rn
            FROM market.price_daily
            WHERE instrument_id IN :instrument_ids
              AND trade_date < :cutoff
        )
        SELECT instrument_id, trade_date, close_price
        FROM ranked
        WHERE rn <= :limit_per_symbol
        ORDER BY instrument_id, trade_date ASC
        """
    ).bindparams(bindparam("instrument_ids", expanding=True))

    rows = session.execute(
        stmt,
        {
            "instrument_ids": ids,
            "cutoff": today,
            "limit_per_symbol": limit_per_symbol,
        },
    ).mappings().all()

    grouped: dict[int, list[Decimal]] = {iid: [] for iid in ids}
    for row in rows:
        iid = int(row["instrument_id"])
        close = _to_decimal(row["close_price"])
        if close is not None:
            grouped.setdefault(iid, []).append(close)

    for iid in list(grouped.keys()):
        closes = grouped[iid]
        if len(closes) > required:
            grouped[iid] = closes[-required:]
    return grouped
