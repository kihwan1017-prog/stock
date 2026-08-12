"""KRW universe — 기존 market.instrument 재사용 (새 master 테이블 금지)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.markets.models import Instrument


def _is_blocked_by_extra(extra: dict[str, Any]) -> bool:
    """유의/경고/거래중지 메타만 제외 — market_event 구조 오판 방지."""

    warning = extra.get("market_warning")
    if warning is True:
        return True
    if isinstance(warning, str) and warning.strip():
        w = warning.strip().upper()
        if w not in {"NONE", "NULL", "FALSE", "0"}:
            return True

    event = extra.get("market_event")
    if isinstance(event, dict):
        if event.get("warning") is True:
            return True
        # Upbit details: market_event.warning bool
        halt = event.get("halt") or event.get("trading_halt")
        if halt is True:
            return True
    return False


def load_krw_universe(session: Session) -> list[dict[str, Any]]:
    """활성 UPBIT KRW-* instrument 목록."""

    rows = list(
        session.scalars(
            select(Instrument).where(
                Instrument.exchange_code == "UPBIT",
                Instrument.is_active.is_(True),
                Instrument.symbol.like("KRW-%"),
            )
        )
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.symbol or "").upper()
        if not symbol.startswith("KRW-"):
            continue
        extra = row.extra_data if isinstance(row.extra_data, dict) else {}
        if _is_blocked_by_extra(extra):
            continue
        if row.delisted_date is not None:
            continue
        out.append(
            {
                "symbol": symbol,
                "name": row.name,
                "instrument_id": int(row.instrument_id),
                "extra_data": extra,
            }
        )
    return out
