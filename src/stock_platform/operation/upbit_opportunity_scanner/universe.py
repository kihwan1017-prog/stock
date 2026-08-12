"""KRW universe — 기존 market.instrument 재사용 (새 master 테이블 금지)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.markets.models import Instrument
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    DEFAULT_STABLECOIN_BASE_ASSETS,
    STABLECOIN_NAME_KEYWORDS,
)


def _has_active_caution(extra: dict[str, Any]) -> bool:
    """market_event.caution 플래그 중 true가 있으면 유의 상태."""

    event = extra.get("market_event")
    if not isinstance(event, dict):
        return False
    caution = event.get("caution")
    if isinstance(caution, bool):
        return caution
    if isinstance(caution, dict):
        return any(bool(v) for v in caution.values())
    return False


def _is_blocked_by_extra(
    extra: dict[str, Any],
    *,
    exclude_caution: bool,
) -> bool:
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
        halt = event.get("halt") or event.get("trading_halt")
        if halt is True:
            return True

    if exclude_caution and _has_active_caution(extra):
        return True
    return False


def is_stablecoin_like(
    *,
    symbol: str,
    extra: dict[str, Any] | None = None,
    stable_bases: frozenset[str] | None = None,
) -> bool:
    """베이스 자산 카테고리 + english_name 메타 기반 스테이블 판별."""

    bases = stable_bases or DEFAULT_STABLECOIN_BASE_ASSETS
    sym = str(symbol or "").upper()
    if "-" in sym:
        base = sym.split("-", 1)[1]
    else:
        base = sym
    if base in bases:
        return True

    extra = extra or {}
    english = str(extra.get("english_name") or "").lower()
    if english and any(k in english for k in STABLECOIN_NAME_KEYWORDS):
        return True
    return False


def load_krw_universe(
    session: Session,
    *,
    exclude_caution: bool = True,
    exclude_stablecoins: bool = True,
    stable_bases: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
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
        if _is_blocked_by_extra(extra, exclude_caution=exclude_caution):
            continue
        if row.delisted_date is not None:
            continue
        if exclude_stablecoins and is_stablecoin_like(
            symbol=symbol,
            extra=extra,
            stable_bases=stable_bases,
        ):
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
