"""KIWOOM multi-symbol date helpers — heavy realtime import 회피."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def today_kst(now: datetime | None = None) -> date:
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(KST).date()
