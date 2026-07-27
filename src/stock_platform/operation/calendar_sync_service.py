"""STEP 8-5-7 — KRX Trading Calendar Sync (큐레이션 + 주말/평일 생성)."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.operation.calendar_audit import audit_calendar_event
from stock_platform.operation.calendar_constants import (
    DEFAULT_KRX_REGULAR_CLOSE,
    DEFAULT_KRX_REGULAR_OPEN,
    CalendarSessionType,
    CalendarVerifiedStatus,
    KRX_TIMEZONE,
)
from stock_platform.operation.calendar_krx_holidays import (
    curated_krx_holidays_for_years,
    curated_year_coverage,
)
from stock_platform.operation.calendar_repository import (
    TradingCalendarRepository,
)
from stock_platform.operation.calendar_service import (
    TradingCalendarService,
)

logger = logging.getLogger(__name__)


def _parse_hms(value: str) -> time:
    parts = value.split(":")
    return time(int(parts[0]), int(parts[1]), int(parts[2] if len(parts) > 2 else 0))


class TradingCalendarSyncService:
    """
    원천: CURATED_KR_HOLIDAY + GENERATED_WEEKDAY/WEEKEND.

    HTML 스크래핑 없음. 기존 VERIFIED MANUAL 행은 삭제·강제 휴장 전환 금지.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = TradingCalendarRepository(session)

    def build_krx_rows(
        self,
        *,
        from_date: date,
        to_date: date,
        mark_verified: bool = True,
        actor: str = "system:sync",
    ) -> list[dict[str, Any]]:
        years = list(range(from_date.year, to_date.year + 1))
        holidays = curated_krx_holidays_for_years(years)
        open_t = _parse_hms(DEFAULT_KRX_REGULAR_OPEN)
        close_t = _parse_hms(DEFAULT_KRX_REGULAR_CLOSE)
        now = datetime.now(timezone.utc)
        verified = (
            CalendarVerifiedStatus.VERIFIED.value
            if mark_verified
            else CalendarVerifiedStatus.UNVERIFIED.value
        )
        rows: list[dict[str, Any]] = []
        current = from_date
        while current <= to_date:
            is_weekend = current.weekday() >= 5
            holiday_name = holidays.get(current)
            is_closed = is_weekend or holiday_name is not None
            if is_closed:
                session_type = CalendarSessionType.CLOSED.value
                source_type = (
                    "CURATED_KR_HOLIDAY"
                    if holiday_name
                    else "GENERATED_WEEKEND"
                )
                source_code = source_type
                closure = holiday_name or "WEEKEND"
            else:
                session_type = CalendarSessionType.REGULAR.value
                source_type = "GENERATED_WEEKDAY"
                source_code = source_type
                closure = None
            rows.append(
                {
                    "exchange_code": "KRX",
                    "calendar_date": current,
                    "is_trading_day": not is_closed,
                    "holiday_name": holiday_name,
                    "source_code": source_code,
                    "session_type": session_type,
                    "preopen_at": time(8, 0) if not is_closed else None,
                    "regular_open_at": open_t if not is_closed else None,
                    "regular_close_at": close_t if not is_closed else None,
                    "after_hours_close_at": None,
                    "timezone": KRX_TIMEZONE,
                    "closure_reason": closure,
                    "source_type": source_type,
                    "source_reference": (
                        f"curated:{curated_year_coverage()[0]}"
                        f"-{curated_year_coverage()[1]}"
                    ),
                    "source_updated_at": now,
                    "verified_status": verified,
                    "verified_by": actor if mark_verified else None,
                    "verified_at": now if mark_verified else None,
                }
            )
            current += timedelta(days=1)
        return rows

    def sync_krx(
        self,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        trigger_type: str = "MANUAL",
        requested_by: str | None = None,
        mark_verified: bool = True,
        past_years: int = 1,
        future_days: int | None = None,
    ) -> dict[str, Any]:
        from stock_platform.common.settings import get_settings

        settings = get_settings()
        today = datetime.now(
            __import__("zoneinfo").ZoneInfo(KRX_TIMEZONE)
        ).date()
        if future_days is None:
            future_days = int(settings.krx_calendar_required_future_days)
        if from_date is None:
            from_date = date(today.year - max(0, past_years), 1, 1)
        if to_date is None:
            to_date = today + timedelta(days=max(1, future_days))

        audit_calendar_event(
            "CALENDAR_SYNC_STARTED",
            actor=requested_by or "system",
            detail={
                "exchange_code": "KRX",
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "trigger_type": trigger_type,
            },
        )
        run = self._repo.start_sync_run(
            exchange_code="KRX",
            trigger_type=trigger_type,
            requested_by=requested_by,
            from_date=from_date,
            to_date=to_date,
        )
        try:
            rows = self.build_krx_rows(
                from_date=from_date,
                to_date=to_date,
                mark_verified=mark_verified,
                actor=requested_by or "system:sync",
            )
            upserted, conflicts = (
                self._repo.upsert_generated_preserving_manual(rows)
            )
            self._session.commit()
            coverage = TradingCalendarService(
                self._repo
            ).validate_calendar_coverage("KRX", from_date, to_date)
            payload = {
                "upserted_count": upserted,
                "conflict_count": conflicts,
                "coverage_complete": coverage.coverage_complete,
                "live_trading_allowed": coverage.live_trading_allowed,
                "message": coverage.message,
            }
            self._repo.finish_sync_run(
                run,
                status_code="SUCCESS",
                upserted_count=upserted,
                conflict_count=conflicts,
                result_payload=payload,
            )
            audit_calendar_event(
                "CALENDAR_SYNC_COMPLETED",
                actor=requested_by or "system",
                detail={
                    "exchange_code": "KRX",
                    "sync_run_id": int(run.sync_run_id),
                    **payload,
                },
            )
            if conflicts:
                audit_calendar_event(
                    "CALENDAR_SOURCE_CONFLICT",
                    actor=requested_by or "system",
                    detail={
                        "exchange_code": "KRX",
                        "conflict_count": conflicts,
                    },
                )
            return {
                "status": "SUCCESS",
                "sync_run_id": int(run.sync_run_id),
                **payload,
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
            }
        except Exception as exc:
            self._session.rollback()
            self._repo.finish_sync_run(
                run,
                status_code="FAILED",
                error_message=str(exc)[:2000],
            )
            audit_calendar_event(
                "CALENDAR_SYNC_FAILED",
                actor=requested_by or "system",
                detail={
                    "exchange_code": "KRX",
                    "error": str(exc)[:500],
                },
            )
            raise

    def check_coverage(self) -> dict[str, Any]:
        from stock_platform.common.settings import get_settings

        settings = get_settings()
        today = datetime.now(
            __import__("zoneinfo").ZoneInfo(KRX_TIMEZONE)
        ).date()
        future = int(settings.krx_calendar_required_future_days)
        report = TradingCalendarService(self._repo).validate_calendar_coverage(
            "KRX",
            today,
            today + timedelta(days=future),
        )
        latest = self._repo.latest_sync_run("KRX")
        max_date = self._repo.max_verified_date("KRX")
        return {
            "exchange_code": "KRX",
            "required_future_days": future,
            "coverage": {
                "from_date": report.from_date.isoformat(),
                "to_date": report.to_date.isoformat(),
                "expected_calendar_days": report.expected_calendar_days,
                "stored_days": report.stored_days,
                "missing_days": report.missing_days,
                "verified_trading_days": report.verified_trading_days,
                "coverage_complete": report.coverage_complete,
                "by_verified_status": report.by_verified_status,
                "live_trading_allowed": report.live_trading_allowed,
                "message": report.message,
            },
            "max_verified_date": (
                max_date.isoformat() if max_date else None
            ),
            "last_sync": (
                {
                    "sync_run_id": int(latest.sync_run_id),
                    "status_code": latest.status_code,
                    "started_at": latest.started_at.isoformat()
                    if latest.started_at
                    else None,
                    "finished_at": latest.finished_at.isoformat()
                    if latest.finished_at
                    else None,
                    "upserted_count": latest.upserted_count,
                }
                if latest
                else None
            ),
        }
