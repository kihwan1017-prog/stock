"""숫자·보유시간·심볼 표시 헬퍼."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from stock_platform.notification.formatting import (
    format_krw,
    format_number,
    format_symbol,
)


def to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def format_signed_krw(value: Any) -> str:
    num = to_decimal(value)
    if num is None:
        return "-"
    sign = "+" if num > 0 else ""
    # format_krw는 부호 없음
    body = format_krw(abs(num))
    if num < 0:
        return f"-{body}"
    return f"{sign}{body}"


def format_signed_percent(value: Any, *, already_percent: bool = True) -> str:
    """PnL%는 이미 퍼센트 단위(0.51 → 0.51%)로 전달되는 경우가 많음."""

    num = to_decimal(value)
    if num is None:
        return "-"
    pct = num if already_percent else num * Decimal("100")
    sign = "+" if pct > 0 else ""
    q = pct.quantize(Decimal("0.01"))
    return f"{sign}{q}%"


def format_qty_trim(value: Any) -> str:
    num = to_decimal(value)
    if num is None:
        return "-"
    text = format_number(num)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def format_holding_duration(seconds: Any) -> str:
    try:
        sec = int(seconds)
    except (TypeError, ValueError):
        return "-"
    if sec < 0:
        sec = 0
    if sec < 60:
        return f"{sec}초"
    minutes, s = divmod(sec, 60)
    if minutes < 60:
        return f"{minutes}분 {s}초" if s else f"{minutes}분"
    hours, m = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}시간 {m}분" if m else f"{hours}시간"
    days, h = divmod(hours, 24)
    return f"{days}일 {h}시간 {m}분" if m or h else f"{days}일"


def symbol_line(symbol: Any, *, name: str | None = None) -> str:
    """리플 (KRW-XRP) 형태. name 없으면 symbol만."""

    raw = str(symbol or "").strip()
    if not raw:
        return "-"
    if name:
        # format_symbol은 KRW- 제거하므로 전체 표기 직접
        return f"{name} ({raw})"
    return format_symbol(raw) if raw.startswith("KRW-") else raw
