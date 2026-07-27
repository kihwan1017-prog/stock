from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_platform.operation.calendar_constants import (
    CalendarSessionType,
    CalendarVerifiedStatus,
)
from stock_platform.operation.calendar_models import (
    TradingCalendarDay,
    TradingCalendarSyncRun,
)


class TradingCalendarRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_days(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0

        stmt = insert(TradingCalendarDay).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                TradingCalendarDay.exchange_code,
                TradingCalendarDay.calendar_date,
            ],
            set_={
                "is_trading_day": stmt.excluded.is_trading_day,
                "holiday_name": stmt.excluded.holiday_name,
                "source_code": stmt.excluded.source_code,
                "session_type": stmt.excluded.session_type,
                "preopen_at": stmt.excluded.preopen_at,
                "regular_open_at": stmt.excluded.regular_open_at,
                "regular_close_at": stmt.excluded.regular_close_at,
                "after_hours_close_at": (
                    stmt.excluded.after_hours_close_at
                ),
                "timezone": stmt.excluded.timezone,
                "closure_reason": stmt.excluded.closure_reason,
                "source_type": stmt.excluded.source_type,
                "source_reference": stmt.excluded.source_reference,
                "source_updated_at": stmt.excluded.source_updated_at,
                "verified_status": stmt.excluded.verified_status,
                "verified_by": stmt.excluded.verified_by,
                "verified_at": stmt.excluded.verified_at,
                "updated_at": datetime.now(timezone.utc),
            },
            # MANUAL VERIFIED 행을 Sync가 함부로 덮어쓰지 않도록
            # where: 기존이 MANUAL+VERIFIED이면 skip은 SQL로 어려워
            # Sync 서비스에서 충돌 감지 후 CONFLICT 처리
        )
        result = self._session.execute(stmt)
        self._session.commit()
        return int(result.rowcount or len(rows))

    def upsert_generated_preserving_manual(
        self, rows: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """MANUAL VERIFIED 행은 유지, 나머지는 upsert. 충돌 수 반환."""

        upserted = 0
        conflicts = 0
        to_upsert: list[dict[str, Any]] = []
        for row in rows:
            existing = self.get_day(
                exchange_code=row["exchange_code"],
                calendar_date=row["calendar_date"],
            )
            if (
                existing is not None
                and existing.source_type == "MANUAL"
                and existing.verified_status
                == CalendarVerifiedStatus.VERIFIED.value
            ):
                if (
                    bool(existing.is_trading_day)
                    != bool(row["is_trading_day"])
                    or (existing.session_type or "")
                    != (row.get("session_type") or "")
                ):
                    existing.verified_status = (
                        CalendarVerifiedStatus.CONFLICT.value
                    )
                    existing.updated_at = datetime.now(timezone.utc)
                    conflicts += 1
                continue
            to_upsert.append(row)

        # 배치 upsert (commit은 호출측)
        if to_upsert:
            chunk = 200
            for i in range(0, len(to_upsert), chunk):
                part = to_upsert[i : i + chunk]
                stmt = insert(TradingCalendarDay).values(part)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[
                        TradingCalendarDay.exchange_code,
                        TradingCalendarDay.calendar_date,
                    ],
                    set_={
                        "is_trading_day": stmt.excluded.is_trading_day,
                        "holiday_name": stmt.excluded.holiday_name,
                        "source_code": stmt.excluded.source_code,
                        "session_type": stmt.excluded.session_type,
                        "preopen_at": stmt.excluded.preopen_at,
                        "regular_open_at": stmt.excluded.regular_open_at,
                        "regular_close_at": stmt.excluded.regular_close_at,
                        "after_hours_close_at": (
                            stmt.excluded.after_hours_close_at
                        ),
                        "timezone": stmt.excluded.timezone,
                        "closure_reason": stmt.excluded.closure_reason,
                        "source_type": stmt.excluded.source_type,
                        "source_reference": stmt.excluded.source_reference,
                        "source_updated_at": stmt.excluded.source_updated_at,
                        "verified_status": stmt.excluded.verified_status,
                        "verified_by": stmt.excluded.verified_by,
                        "verified_at": stmt.excluded.verified_at,
                        "updated_at": datetime.now(timezone.utc),
                    },
                )
                self._session.execute(stmt)
                upserted += len(part)
        self._session.flush()
        return upserted, conflicts

    def get_day(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
    ) -> TradingCalendarDay | None:
        return self._session.scalar(
            select(TradingCalendarDay).where(
                TradingCalendarDay.exchange_code
                == exchange_code.upper(),
                TradingCalendarDay.calendar_date == calendar_date,
            )
        )

    def list_between(
        self,
        *,
        exchange_code: str,
        start_date: date,
        end_date: date,
        verified_status: str | None = None,
    ) -> list[TradingCalendarDay]:
        stmt = (
            select(TradingCalendarDay)
            .where(
                TradingCalendarDay.exchange_code
                == exchange_code.upper(),
                TradingCalendarDay.calendar_date >= start_date,
                TradingCalendarDay.calendar_date <= end_date,
            )
            .order_by(TradingCalendarDay.calendar_date.asc())
        )
        if verified_status:
            stmt = stmt.where(
                TradingCalendarDay.verified_status == verified_status
            )
        return list(self._session.scalars(stmt))

    def verify_day(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
        actor: str,
        status: str = CalendarVerifiedStatus.VERIFIED.value,
    ) -> TradingCalendarDay | None:
        row = self.get_day(
            exchange_code=exchange_code,
            calendar_date=calendar_date,
        )
        if row is None:
            return None
        row.verified_status = status
        row.verified_by = actor
        row.verified_at = datetime.now(timezone.utc)
        row.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        return row

    def update_day(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
        fields: dict[str, Any],
        actor: str,
        reason: str,
    ) -> TradingCalendarDay | None:
        row = self.get_day(
            exchange_code=exchange_code,
            calendar_date=calendar_date,
        )
        if row is None:
            return None
        for key, value in fields.items():
            if hasattr(row, key) and key not in {
                "calendar_day_id",
                "exchange_code",
                "calendar_date",
            }:
                setattr(row, key, value)
        row.source_type = "MANUAL"
        row.source_code = "MANUAL"
        row.source_reference = f"manual:{reason[:180]}"
        row.source_updated_at = datetime.now(timezone.utc)
        row.verified_status = CalendarVerifiedStatus.UNVERIFIED.value
        row.verified_by = None
        row.verified_at = None
        row.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        return row

    def coverage_stats(
        self,
        *,
        exchange_code: str,
        from_date: date,
        to_date: date,
    ) -> dict[str, Any]:
        rows = self.list_between(
            exchange_code=exchange_code,
            start_date=from_date,
            end_date=to_date,
        )
        by_status: dict[str, int] = {}
        trading = 0
        for row in rows:
            by_status[row.verified_status] = (
                by_status.get(row.verified_status, 0) + 1
            )
            if (
                row.is_trading_day
                and row.verified_status
                == CalendarVerifiedStatus.VERIFIED.value
            ):
                trading += 1
        expected_days = (to_date - from_date).days + 1
        return {
            "exchange_code": exchange_code.upper(),
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "expected_calendar_days": expected_days,
            "stored_days": len(rows),
            "missing_days": max(0, expected_days - len(rows)),
            "verified_trading_days": trading,
            "by_verified_status": by_status,
            "coverage_complete": len(rows) >= expected_days
            and by_status.get(
                CalendarVerifiedStatus.VERIFIED.value, 0
            )
            >= expected_days,
        }

    def start_sync_run(
        self,
        *,
        exchange_code: str,
        trigger_type: str,
        requested_by: str | None,
        from_date: date,
        to_date: date,
    ) -> TradingCalendarSyncRun:
        run = TradingCalendarSyncRun(
            exchange_code=exchange_code.upper(),
            status_code="RUNNING",
            trigger_type=trigger_type,
            requested_by=requested_by,
            from_date=from_date,
            to_date=to_date,
        )
        self._session.add(run)
        self._session.commit()
        self._session.refresh(run)
        return run

    def finish_sync_run(
        self,
        run: TradingCalendarSyncRun,
        *,
        status_code: str,
        upserted_count: int = 0,
        conflict_count: int = 0,
        error_message: str | None = None,
        result_payload: dict[str, Any] | None = None,
    ) -> None:
        run.status_code = status_code
        run.upserted_count = upserted_count
        run.conflict_count = conflict_count
        run.error_message = error_message
        run.result_payload = result_payload or {}
        run.finished_at = datetime.now(timezone.utc)
        self._session.add(run)
        self._session.commit()

    def latest_sync_run(
        self, exchange_code: str = "KRX"
    ) -> TradingCalendarSyncRun | None:
        return self._session.scalar(
            select(TradingCalendarSyncRun)
            .where(
                TradingCalendarSyncRun.exchange_code
                == exchange_code.upper()
            )
            .order_by(TradingCalendarSyncRun.started_at.desc())
            .limit(1)
        )

    def max_verified_date(
        self, exchange_code: str = "KRX"
    ) -> date | None:
        return self._session.scalar(
            select(TradingCalendarDay.calendar_date)
            .where(
                TradingCalendarDay.exchange_code
                == exchange_code.upper(),
                TradingCalendarDay.verified_status
                == CalendarVerifiedStatus.VERIFIED.value,
            )
            .order_by(TradingCalendarDay.calendar_date.desc())
            .limit(1)
        )
