"""Research-only Upbit 1m candle store (SQLite). Never writes market.candle_minute."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

DEFAULT_DB = Path(".run/research_candles/upbit_minute_research.sqlite")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS candle_minute (
            symbol TEXT NOT NULL,
            candle_at TEXT NOT NULL,
            open_price REAL NOT NULL,
            high_price REAL NOT NULL,
            low_price REAL NOT NULL,
            close_price REAL NOT NULL,
            volume REAL NOT NULL,
            trade_value REAL NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY (symbol, candle_at)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_cm_sym_at ON candle_minute(symbol, candle_at)"
    )
    conn.commit()
    return conn


def upsert_rows(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    rows: Sequence[dict[str, Any]],
    source: str,
) -> int:
    """Insert-or-ignore research candles."""

    sym = symbol.upper()
    n = 0
    for r in rows:
        at = _as_utc(r["candle_at"]).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            """
            INSERT OR IGNORE INTO candle_minute(
                symbol, candle_at, open_price, high_price, low_price,
                close_price, volume, trade_value, source
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                sym,
                at,
                float(r["open_price"]),
                float(r["high_price"]),
                float(r["low_price"]),
                float(r["close_price"]),
                float(r.get("volume") or 0),
                float(r.get("trade_value") or 0),
                source,
            ),
        )
        n += conn.total_changes  # not accurate per row; recount below
    conn.commit()
    return len(rows)


def coverage(conn: sqlite3.Connection, symbol: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT COUNT(*), MIN(candle_at), MAX(candle_at)
        FROM candle_minute WHERE symbol=?
        """,
        (symbol.upper(),),
    ).fetchone()
    return {
        "symbol": symbol.upper(),
        "n": int(row[0] or 0),
        "min": row[1],
        "max": row[2],
    }


def load_symbol_bars(
    conn: sqlite3.Connection,
    symbol: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    clauses = ["symbol=?"]
    params: list[Any] = [symbol.upper()]
    if start is not None:
        clauses.append("candle_at >= ?")
        params.append(_as_utc(start).strftime("%Y-%m-%dT%H:%M:%SZ"))
    if end is not None:
        clauses.append("candle_at <= ?")
        params.append(_as_utc(end).strftime("%Y-%m-%dT%H:%M:%SZ"))
    sql = (
        "SELECT candle_at, open_price, high_price, low_price, close_price, "
        "volume, trade_value FROM candle_minute WHERE "
        + " AND ".join(clauses)
        + " ORDER BY candle_at"
    )
    out = []
    for r in conn.execute(sql, params):
        at = datetime.fromisoformat(str(r[0]).replace("Z", "+00:00"))
        out.append(
            {
                "candle_at": at,
                "open_price": r[1],
                "high_price": r[2],
                "low_price": r[3],
                "close_price": r[4],
                "volume": r[5],
                "trade_value": r[6],
            }
        )
    return out


def global_span(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT COUNT(*), MIN(candle_at), MAX(candle_at), COUNT(DISTINCT symbol) FROM candle_minute"
    ).fetchone()
    return {
        "n": int(row[0] or 0),
        "min": row[1],
        "max": row[2],
        "symbols": int(row[3] or 0),
    }
