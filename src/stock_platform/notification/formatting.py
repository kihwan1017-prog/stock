"""알림용 숫자/시각/심볼 포맷터 — LLM 없음."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")


def format_krw(value: Any) -> str:
    """10000 → '10,000원'."""

    num = _to_decimal(value)
    if num is None:
        return "-"
    quantized = num.quantize(Decimal("1")) if num == num.to_integral() else num
    text = f"{quantized:,}"
    return f"{text}원"


def format_number(value: Any, *, digits: int | None = None) -> str:
    num = _to_decimal(value)
    if num is None:
        return "-"
    if digits is not None:
        q = Decimal(10) ** -digits
        num = num.quantize(q)
        return f"{num:f}"
    if num == num.to_integral():
        return f"{int(num):,}"
    return f"{num:,}"


def format_quantity(value: Any) -> str:
    return format_number(value)


def format_percent(value: Any) -> str:
    """0.95 → '95%' / 95 → '95%'."""

    num = _to_decimal(value)
    if num is None:
        return "-"
    if abs(num) <= Decimal("1"):
        num = num * Decimal("100")
    # 정수면 소수점 제거
    if num == num.to_integral():
        return f"{int(num)}%"
    return f"{num.quantize(Decimal('0.01'))}%"


def format_datetime_kst(value: Any) -> str:
    dt = _to_datetime(value)
    if dt is None:
        return "-"
    return dt.astimezone(_KST).strftime("%Y-%m-%d %H:%M:%S KST")


def format_symbol(symbol: Any, *, name: str | None = None) -> str:
    raw = str(symbol or "").strip().upper()
    if not raw:
        return "-"
    display = raw
    if raw.startswith("KRW-"):
        display = raw[4:]
    if name:
        return f"{display} ({name})"
    return display


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None
