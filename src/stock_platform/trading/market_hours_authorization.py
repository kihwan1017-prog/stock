"""KRX market-hours ceiling helpers for unattended MARKET_HOURS mode.

TradingCalendarService SoT — 하드코딩 now 비교만으로 장중 판정하지 않음.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from stock_platform.trading.live_session_expiry import aware_utc

_KST = ZoneInfo("Asia/Seoul")


def krx_market_hours_state(
    session: Session,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """정규장 여부·ceiling(당일 regular_close KST→UTC) 반환."""

    now_utc = aware_utc(now) or datetime.now(timezone.utc)
    now_kst = now_utc.astimezone(_KST)
    calendar_date = now_kst.date()

    from stock_platform.operation.calendar_constants import (
        CalendarSessionType,
    )
    from stock_platform.operation.calendar_repository import (
        TradingCalendarRepository,
    )
    from stock_platform.operation.calendar_service import (
        TradingCalendarService,
    )

    decision = TradingCalendarService(
        TradingCalendarRepository(session)
    ).evaluate(
        exchange_code="KRX",
        calendar_date=calendar_date,
    )
    open_t = decision.regular_open_at or time(9, 0)
    close_t = decision.regular_close_at or time(15, 30)
    open_kst = datetime.combine(calendar_date, open_t, tzinfo=_KST)
    close_kst = datetime.combine(calendar_date, close_t, tzinfo=_KST)
    open_utc = open_kst.astimezone(timezone.utc)
    close_utc = close_kst.astimezone(timezone.utc)

    is_trading_day = bool(decision.is_trading_day)
    session_type = str(decision.session_type or "").upper()
    regular = session_type == CalendarSessionType.REGULAR.value or (
        is_trading_day and session_type in {"", "REGULAR"}
    )
    in_regular = bool(
        is_trading_day
        and regular
        and open_kst <= now_kst <= close_kst
    )
    past_close = bool(is_trading_day and now_kst > close_kst)
    before_open = bool(is_trading_day and now_kst < open_kst)

    return {
        "exchange": "KRX",
        "calendar_date": calendar_date.isoformat(),
        "is_trading_day": is_trading_day,
        "session_type": session_type or None,
        "reason_code": str(decision.reason_code or ""),
        "regular_open_at": open_t.isoformat(timespec="minutes"),
        "regular_close_at": close_t.isoformat(timespec="minutes"),
        "regular_open_at_utc": open_utc.isoformat(),
        "regular_close_at_utc": close_utc.isoformat(),
        "in_regular_session": in_regular,
        "past_close": past_close,
        "before_open": before_open,
        "now_kst": now_kst.isoformat(),
        "ceiling_utc": close_utc if is_trading_day else None,
    }


def market_hours_authorized_until(
    session: Session,
    *,
    now: datetime | None = None,
) -> datetime:
    """당일 정규장 마감(UTC). 장 아니면 ValueError."""

    state = krx_market_hours_state(session, now=now)
    if not state["is_trading_day"]:
        raise ValueError(f"NOT_TRADING_DAY:{state.get('reason_code')}")
    if not state["in_regular_session"]:
        raise ValueError(
            "NOT_IN_REGULAR_SESSION:"
            f"past_close={state['past_close']} before_open={state['before_open']}"
        )
    ceiling = state["ceiling_utc"]
    if ceiling is None:
        raise ValueError("NO_CEILING")
    now_utc = aware_utc(now) or datetime.now(timezone.utc)
    # 최소 60초 horizon — 마감 직전 enable 방지에 가까운 방어
    if ceiling <= now_utc + timedelta(seconds=60):
        raise ValueError("CEILING_TOO_NEAR")
    return ceiling
