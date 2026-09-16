"""Daily order limit V2 — submit vs filled-entry semantics.

V1 (ORDER_LIMIT_V1_SUBMIT_ONLY):
  UBA-wide TradingOrder CREATE count vs daily_order_limit
  (cancelled-after-submit still counts). 2026-08-21 및 V2 미옵트인 유지.

V2 (ORDER_LIMIT_V2_SUBMIT_AND_FILLED_ENTRY):
  strategy-owned ENTRY submit_count / filled_entry_count
  effective trading_date >= 2026-08-22 이고 admin이 V2 limit를 명시한 경우만.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

ORDER_LIMIT_V1 = "ORDER_LIMIT_V1_SUBMIT_ONLY"
ORDER_LIMIT_V2 = "ORDER_LIMIT_V2_SUBMIT_AND_FILLED_ENTRY"

# V2 semantics 적용 가능 최초 trading date (KST). 당일 중간 mixing 금지.
ORDER_LIMIT_V2_MIN_TRADING_DATE = date(2026, 8, 22)

# UI recommended only — auto-apply 금지
RECOMMENDED_DAILY_SUBMIT_LIMIT = 5
RECOMMENDED_DAILY_FILLED_ENTRY_LIMIT = 1

REASON_DAILY_SUBMIT_LIMIT = "DAILY_SUBMIT_LIMIT_REACHED"
REASON_DAILY_FILLED_ENTRY_LIMIT = "DAILY_FILLED_ENTRY_LIMIT_REACHED"
# legacy alias (V1 / backward compatible)
REASON_DAILY_ORDER_LIMIT = "DAILY_ORDER_LIMIT_EXCEEDED"


def trading_date_kst(now: datetime | None = None) -> date:
    moment = now or datetime.now(tz=KST)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=KST)
    return moment.astimezone(KST).date()


@dataclass(frozen=True, slots=True)
class OrderLimitDecision:
    """게이트 판정 결과."""

    policy_version: str
    use_v2: bool
    submit_limit: int
    filled_entry_limit: int
    submit_count: int
    filled_entry_count: int
    blocked: bool
    reason_code: str | None
    detail: dict[str, Any]


def is_v2_eligible_trading_date(trading_date: date) -> bool:
    return trading_date >= ORDER_LIMIT_V2_MIN_TRADING_DATE


def resolve_order_limit_policy_version(
    *,
    trading_date: date,
    daily_submit_limit: int | None,
    daily_filled_entry_limit: int | None,
) -> str:
    """당일 V1 고정 또는 admin V2 옵트인 시에만 V2."""

    if not is_v2_eligible_trading_date(trading_date):
        return ORDER_LIMIT_V1
    if daily_submit_limit is None and daily_filled_entry_limit is None:
        return ORDER_LIMIT_V1
    return ORDER_LIMIT_V2


def effective_v2_limits(
    *,
    daily_order_limit: int,
    daily_submit_limit: int | None,
    daily_filled_entry_limit: int | None,
) -> tuple[int, int]:
    """V2 활성 시 명시값 우선, 미설정 축은 legacy daily_order_limit fallback.

    자동 완화(5/1 강제) 금지 — admin 미설정 축은 기존한도 유지.
    """

    legacy = max(0, int(daily_order_limit))
    submit = (
        int(daily_submit_limit)
        if daily_submit_limit is not None
        else legacy
    )
    filled = (
        int(daily_filled_entry_limit)
        if daily_filled_entry_limit is not None
        else legacy
    )
    return max(0, submit), max(0, filled)


def parse_strategy_id(strategy_id: Any) -> int | None:
    if strategy_id is None:
        return None
    raw = str(strategy_id).strip()
    if not raw or not raw.isdigit():
        return None
    value = int(raw)
    return value if value > 0 else None
