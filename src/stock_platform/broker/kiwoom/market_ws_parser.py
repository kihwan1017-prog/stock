"""KIWOOM 시장 시세 WS 메시지 정규화 (type=0B 주식체결)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from stock_platform.broker.kiwoom.market_realtime_contract import (
    FIELD_ACCUM_VOLUME,
    FIELD_BEST_ASK,
    FIELD_BEST_BID,
    FIELD_CHANGE_RATE,
    FIELD_CURRENT_PRICE,
    FIELD_TRADE_TIME,
    FIELD_TRADE_VOLUME,
    MARKET_TRADE_TYPE,
    source_code_for_environment,
)
from stock_platform.broker.kiwoom.price import normalize_kiwoom_price
from stock_platform.realtime.models import MarketEventType, RealtimeQuote


def login_ack_ok(message: dict[str, Any]) -> bool:
    if str(message.get("trnm") or "").upper() != "LOGIN":
        return False
    try:
        return int(message.get("return_code", -1)) == 0
    except (TypeError, ValueError):
        return False


def reg_ack_ok(message: dict[str, Any]) -> bool:
    if str(message.get("trnm") or "").upper() != "REG":
        return False
    try:
        return int(message.get("return_code", -1)) == 0
    except (TypeError, ValueError):
        return False


def is_ping(message: dict[str, Any]) -> bool:
    return str(message.get("trnm") or "").upper() == "PING"


def is_real_tick(message: dict[str, Any]) -> bool:
    return str(message.get("trnm") or "").upper() == "REAL"


def build_login_payload(token: str) -> dict[str, str]:
    return {"trnm": "LOGIN", "token": token}


def build_market_reg_payload(
    symbols: list[str] | set[str],
    *,
    grp_no: str = "1",
    refresh: str = "1",
    type_code: str = MARKET_TRADE_TYPE,
) -> dict[str, Any]:
    """공식 REG. item에 종목코드 필수. 빈 item(주문체결 00) 금지."""

    items = _clean_symbols(symbols)
    if not items:
        raise ValueError("market REG requires at least one symbol item")
    type_u = str(type_code or "").strip().upper()
    if type_u == "00":
        raise ValueError("market REG must not use execution type 00")
    if type_u != MARKET_TRADE_TYPE:
        raise ValueError(
            f"unsupported market realtime type={type_u!r}; "
            f"official contract is {MARKET_TRADE_TYPE}"
        )
    return {
        "trnm": "REG",
        "grp_no": str(grp_no),
        "refresh": str(refresh),
        "data": [{"item": items, "type": [MARKET_TRADE_TYPE]}],
    }


def build_market_remove_payload(
    symbols: list[str] | set[str],
    *,
    grp_no: str = "1",
    type_code: str = MARKET_TRADE_TYPE,
) -> dict[str, Any]:
    payload = build_market_reg_payload(
        symbols, grp_no=grp_no, refresh="0", type_code=type_code
    )
    payload["trnm"] = "REMOVE"
    return payload


def parse_kiwoom_trade_time(value: Any) -> datetime:
    """체결시간(20). canonical: YYYYMMDDHHMMSS 또는 HHMMSS."""

    now = datetime.now(timezone.utc)
    if value in (None, ""):
        return now
    text = str(value).strip()
    for fmt in ("%Y%m%d%H%M%S", "%H%M%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%H%M%S":
                parsed = parsed.replace(
                    year=now.year, month=now.month, day=now.day
                )
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return now


def _optional_volume(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text.replace("+", ""))
    except Exception:  # noqa: BLE001
        return None


def parse_0b_values_to_quote(
    *,
    item: str,
    values: dict[str, Any],
    environment: str,
    received_at: datetime | None = None,
) -> RealtimeQuote | None:
    symbol = str(item or "").strip().upper()
    if not symbol:
        return None
    price = normalize_kiwoom_price(values.get(FIELD_CURRENT_PRICE))
    if price is None or price <= 0:
        return None
    now = received_at or datetime.now(timezone.utc)
    change_rate = _optional_volume(values.get(FIELD_CHANGE_RATE))
    bid = normalize_kiwoom_price(values.get(FIELD_BEST_BID))
    ask = normalize_kiwoom_price(values.get(FIELD_BEST_ASK))
    if bid is not None and bid <= 0:
        bid = None
    if ask is not None and ask <= 0:
        ask = None
    return RealtimeQuote(
        exchange_code="KRX",
        symbol=symbol,
        event_type=MarketEventType.TRADE,
        trade_price=price,
        opening_price=None,
        high_price=None,
        low_price=None,
        previous_close_price=None,
        change_price=None,
        change_rate=change_rate,
        accumulated_volume=_optional_volume(values.get(FIELD_ACCUM_VOLUME)),
        trade_volume=_optional_volume(values.get(FIELD_TRADE_VOLUME)),
        event_time=parse_kiwoom_trade_time(values.get(FIELD_TRADE_TIME)),
        received_at=now,
        source_code=source_code_for_environment(environment),
        bid=bid,
        ask=ask,
    )


def parse_market_message(
    message: dict[str, Any],
    *,
    environment: str,
    received_at: datetime | None = None,
) -> list[RealtimeQuote]:
    """REAL type=0B만 Quote로. type=00 주문체결은 무시."""

    if not is_real_tick(message):
        return []
    rows = message.get("data") or []
    if not isinstance(rows, list):
        return []
    quotes: list[RealtimeQuote] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        type_code = str(row.get("type") or "").strip().upper()
        if type_code == "00":
            continue
        if type_code != MARKET_TRADE_TYPE:
            continue
        values = row.get("values") or {}
        if not isinstance(values, dict):
            continue
        quote = parse_0b_values_to_quote(
            item=str(row.get("item") or ""),
            values=values,
            environment=environment,
            received_at=received_at,
        )
        if quote is not None:
            quotes.append(quote)
    return quotes


def _clean_symbols(symbols: list[str] | set[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in symbols:
        code = str(raw or "").strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        ordered.append(code)
    return ordered
