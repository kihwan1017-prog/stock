"""STEP N3 — UPBIT KRW instrument universe for news symbol mapping.

Scanner universe(caution/stable 필터)와 분리 — 공지 대상 종목도 포함.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.markets.models import Instrument
from stock_platform.news.symbol_resolver import (
    AliasEntry,
    InstrumentAlias,
    build_alias_entries,
)


def load_upbit_krw_instruments(
    session: Session,
    *,
    active_only: bool = True,
) -> list[InstrumentAlias]:
    """Canonical source: market.instrument (하드코딩 coin list 금지)."""

    stmt = select(Instrument).where(
        Instrument.exchange_code == "UPBIT",
        Instrument.symbol.like("KRW-%"),
    )
    if active_only:
        stmt = stmt.where(Instrument.is_active.is_(True))
    rows = list(session.scalars(stmt))
    out: list[InstrumentAlias] = []
    for row in rows:
        extra = row.extra_data if isinstance(row.extra_data, dict) else {}
        english = str(extra.get("english_name") or "").strip()
        out.append(
            InstrumentAlias(
                symbol=str(row.symbol).upper(),
                base=str(row.symbol).upper().split("-", 1)[-1],
                korean_name=str(row.name or "").strip(),
                english_name=english,
                is_active=bool(row.is_active),
            )
        )
    return out


def load_alias_index(
    session: Session,
    *,
    active_only: bool = True,
) -> tuple[list[InstrumentAlias], list[AliasEntry]]:
    instruments = load_upbit_krw_instruments(
        session, active_only=active_only
    )
    return instruments, build_alias_entries(instruments)
