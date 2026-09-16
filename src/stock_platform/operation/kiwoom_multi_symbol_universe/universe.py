"""KRX tradable universe — market.instrument 재사용."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.markets.models import Instrument
from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
    EXCHANGE_KRX,
)


def _extra_bool(extra: dict[str, Any], key: str) -> bool:
    val = extra.get(key)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().upper() in {"Y", "YES", "TRUE", "1"}
    return False


def is_kiwoom_autotrade_excluded(
    *,
    asset_type: str,
    extra: dict[str, Any],
) -> bool:
    """broker/DB가 제공하는 범위 내 제외 — 추측 필터 금지."""

    at = str(asset_type or "").upper()
    if at in {"ETF", "INDEX"}:
        return True
    if _extra_bool(extra, "is_etf") or _extra_bool(extra, "is_etn"):
        return True
    # Kiwoom instrument master — market_code 8=ETF (broker 제공 필드)
    market_code = str(extra.get("market_code") or "").strip()
    if market_code in {"8", "60", "70", "90"}:
        return True
    market_name = str(extra.get("market_name") or "").strip().upper()
    if market_name in {"ETF", "ETN", "ELW"}:
        return True
    segment = str(extra.get("market_segment") or extra.get("mrkt_tp") or "")
    if segment in {"ETF", "ETN", "ELW", "SUBSCRIPTION_WARRANT", "8", "60", "70", "90"}:
        return True
    # order_warning / audit — 값이 있으면 제외 (관리·유의 등)
    warn = str(extra.get("order_warning") or extra.get("orderWarning") or "").strip()
    if warn and warn.upper() not in {"0", "NONE", "NULL", "FALSE", ""}:
        return True
    audit = str(extra.get("audit_info") or extra.get("auditInfo") or "").strip()
    if audit and audit not in {"0", "정상"}:
        # auditInfo 비정상 코드 — 구체 매핑 없으면 보수적 제외하지 않고 state만 본다
        pass
    state = str(extra.get("state") or extra.get("trading_status") or "").strip()
    if state and state.upper() in {"DELISTED", "HALT", "SUSPENDED"}:
        return True
    return False


def load_krx_tradable_universe(session: Session) -> list[dict[str, Any]]:
    """KRX 활성 보통주 중심 universe."""

    rows = list(
        session.scalars(
            select(Instrument).where(
                Instrument.exchange_code == EXCHANGE_KRX,
                Instrument.is_active.is_(True),
                Instrument.asset_type == "STOCK",
            )
        )
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.symbol or "").strip().upper()
        if not symbol or len(symbol) != 6 or not symbol.isdigit():
            continue
        extra = row.extra_data if isinstance(row.extra_data, dict) else {}
        if is_kiwoom_autotrade_excluded(asset_type=row.asset_type, extra=extra):
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
