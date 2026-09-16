"""STEP 8-5-11 — Calendar Change Request Service."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.calendar_audit import audit_calendar_event
from stock_platform.operation.calendar_change_constants import (
    ACTIVE_CHANGE_STATUSES,
    CalendarChangeStatus,
    CalendarChangeType,
    CalendarSourceType,
)
from stock_platform.operation.calendar_change_entities import (
    TradingCalendarChangeRequest,
    TradingCalendarDayHistory,
)
from stock_platform.operation.calendar_constants import (
    CalendarSessionType,
    CalendarVerifiedStatus,
)
from stock_platform.operation.calendar_models import TradingCalendarDay
from stock_platform.operation.calendar_repository import (
    TradingCalendarRepository,
)


class CalendarChangeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _time_to_str(value: time | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    return str(value)


def _parse_time(value: Any) -> time | None:
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value
    raw = str(value).strip()
    parts = raw.split(":")
    if len(parts) < 2:
        raise CalendarChangeError(
            "invalid_time", f"Invalid time: {raw[:20]}"
        )
    h, m = int(parts[0]), int(parts[1])
    s = int(parts[2]) if len(parts) > 2 else 0
    return time(h, m, s)


def day_snapshot(row: TradingCalendarDay | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "is_trading_day": bool(row.is_trading_day),
        "session_type": row.session_type,
        "preopen_at": _time_to_str(getattr(row, "preopen_at", None)),
        "regular_open_at": _time_to_str(
            getattr(row, "regular_open_at", None)
        ),
        "regular_close_at": _time_to_str(
            getattr(row, "regular_close_at", None)
        ),
        "after_hours_close_at": _time_to_str(
            getattr(row, "after_hours_close_at", None)
        ),
        "holiday_name": getattr(row, "holiday_name", None),
        "closure_reason": getattr(row, "closure_reason", None),
        "source_type": getattr(row, "source_type", None),
        "source_code": getattr(row, "source_code", None),
        "source_reference": getattr(row, "source_reference", None),
        "verified_status": getattr(row, "verified_status", None),
        "timezone": getattr(row, "timezone", None),
        "revision": int(getattr(row, "revision", 1) or 1),
    }


class TradingCalendarChangeService:
    """변경 요청 → 검증 → 승인 → 원자적 적용."""

    def __init__(
        self,
        session: Session,
        *,
        require_separate_approver: bool = False,
    ) -> None:
        self._session = session
        self._repo = TradingCalendarRepository(session)
        self._require_separate = require_separate_approver

    def create_request(
        self,
        *,
        exchange_code: str,
        market_date: date,
        change_type: str,
        requested_values: dict[str, Any],
        reason: str,
        source_type: str,
        requested_by: str,
        source_reference: str | None = None,
        emergency: bool = False,
        expected_revision: int | None = None,
        rollback_of_request_id: int | None = None,
    ) -> TradingCalendarChangeRequest:
        exchange = exchange_code.strip().upper()
        if exchange != "KRX":
            raise CalendarChangeError(
                "exchange_unsupported", "Only KRX supported"
            )
        if change_type not in {c.value for c in CalendarChangeType}:
            raise CalendarChangeError(
                "invalid_change_type", f"Unknown type: {change_type}"
            )
        if source_type not in {c.value for c in CalendarSourceType}:
            raise CalendarChangeError(
                "invalid_source_type", f"Unknown source: {source_type}"
            )
        reason_clean = (reason or "").strip()
        if len(reason_clean) < 3:
            raise CalendarChangeError(
                "reason_required", "reason min length 3"
            )
        if emergency and not source_reference:
            raise CalendarChangeError(
                "source_required",
                "emergency change requires source_reference",
            )

        current = self._repo.get_day(
            exchange_code=exchange, calendar_date=market_date
        )
        current_snap = day_snapshot(current)
        if expected_revision is None and current is not None:
            expected_revision = int(
                getattr(current, "revision", 1) or 1
            )

        values = dict(requested_values or {})
        self._validate_values(
            change_type=change_type, values=values, current=current_snap
        )

        conflict = self._detect_conflict(
            exchange_code=exchange,
            market_date=market_date,
            change_type=change_type,
        )
        status = (
            CalendarChangeStatus.CONFLICT.value
            if conflict
            else CalendarChangeStatus.DRAFT.value
        )

        row = TradingCalendarChangeRequest(
            exchange_code=exchange,
            market_date=market_date,
            change_type=change_type,
            requested_values=values,
            current_values=current_snap,
            reason=reason_clean,
            source_type=source_type,
            source_reference=source_reference,
            emergency=bool(emergency),
            status=status,
            conflict_message=conflict,
            expected_revision=expected_revision,
            requested_by=requested_by,
            requested_at=datetime.now(timezone.utc),
            rollback_of_request_id=rollback_of_request_id,
        )
        self._session.add(row)
        self._session.flush()
        audit_calendar_event(
            "CALENDAR_CHANGE_REQUEST_CREATED",
            actor=requested_by,
            detail={
                "change_request_id": int(row.change_request_id),
                "exchange_code": exchange,
                "market_date": market_date.isoformat(),
                "change_type": change_type,
                "emergency": bool(emergency),
                "status": status,
            },
        )
        return row

    def submit(
        self, request_id: int, *, actor: str
    ) -> TradingCalendarChangeRequest:
        row = self._require(request_id)
        if row.status not in {
            CalendarChangeStatus.DRAFT.value,
            CalendarChangeStatus.CONFLICT.value,
        }:
            raise CalendarChangeError(
                "invalid_status",
                f"Cannot submit from {row.status}",
            )
        conflict = self._detect_conflict(
            exchange_code=row.exchange_code,
            market_date=row.market_date,
            change_type=row.change_type,
            exclude_id=int(row.change_request_id),
        )
        if conflict:
            row.status = CalendarChangeStatus.CONFLICT.value
            row.conflict_message = conflict
            raise CalendarChangeError("conflict", conflict)
        row.status = CalendarChangeStatus.PENDING_REVIEW.value
        row.conflict_message = None
        row.updated_at = datetime.now(timezone.utc)
        audit_calendar_event(
            "CALENDAR_CHANGE_REQUEST_SUBMITTED",
            actor=actor,
            detail={"change_request_id": request_id},
        )
        return row

    def approve(
        self,
        request_id: int,
        *,
        actor: str,
        comment: str | None = None,
    ) -> TradingCalendarChangeRequest:
        row = self._require(request_id)
        if row.status != CalendarChangeStatus.PENDING_REVIEW.value:
            raise CalendarChangeError(
                "invalid_status",
                f"Cannot approve from {row.status}",
            )
        if (
            self._require_separate
            and row.requested_by == actor
        ):
            raise CalendarChangeError(
                "same_approver_forbidden",
                "Requester cannot approve own request",
            )
        row.status = CalendarChangeStatus.APPROVED.value
        row.reviewed_by = actor
        row.reviewed_at = datetime.now(timezone.utc)
        row.review_comment = comment
        row.updated_at = datetime.now(timezone.utc)
        audit_calendar_event(
            "CALENDAR_CHANGE_REQUEST_APPROVED",
            actor=actor,
            detail={
                "change_request_id": request_id,
                "requested_by": row.requested_by,
                "same_actor": row.requested_by == actor,
            },
        )
        return row

    def reject(
        self,
        request_id: int,
        *,
        actor: str,
        reason: str,
    ) -> TradingCalendarChangeRequest:
        row = self._require(request_id)
        if row.status not in {
            CalendarChangeStatus.PENDING_REVIEW.value,
            CalendarChangeStatus.APPROVED.value,
            CalendarChangeStatus.CONFLICT.value,
        }:
            raise CalendarChangeError(
                "invalid_status",
                f"Cannot reject from {row.status}",
            )
        row.status = CalendarChangeStatus.REJECTED.value
        row.reviewed_by = actor
        row.reviewed_at = datetime.now(timezone.utc)
        row.rejected_reason = (reason or "").strip() or "rejected"
        row.updated_at = datetime.now(timezone.utc)
        audit_calendar_event(
            "CALENDAR_CHANGE_REQUEST_REJECTED",
            actor=actor,
            detail={"change_request_id": request_id},
        )
        return row

    def cancel(
        self, request_id: int, *, actor: str
    ) -> TradingCalendarChangeRequest:
        row = self._require(request_id)
        if row.status in {
            CalendarChangeStatus.APPLIED.value,
            CalendarChangeStatus.APPLIED_WITH_SCHEDULER_ERROR.value,
        }:
            raise CalendarChangeError(
                "invalid_status", "Cannot cancel applied request"
            )
        row.status = CalendarChangeStatus.CANCELLED.value
        row.updated_at = datetime.now(timezone.utc)
        audit_calendar_event(
            "CALENDAR_CHANGE_REQUEST_CANCELLED",
            actor=actor,
            detail={"change_request_id": request_id},
        )
        return row

    def apply(
        self, request_id: int, *, actor: str
    ) -> TradingCalendarChangeRequest:
        """원자적 적용 — Idempotent for already APPLIED."""

        row = self._require(request_id)
        if row.status in {
            CalendarChangeStatus.APPLIED.value,
            CalendarChangeStatus.APPLIED_WITH_SCHEDULER_ERROR.value,
        }:
            return row  # idempotent

        allowed = {
            CalendarChangeStatus.APPROVED.value,
        }
        if row.emergency and row.status in {
            CalendarChangeStatus.DRAFT.value,
            CalendarChangeStatus.PENDING_REVIEW.value,
            CalendarChangeStatus.APPROVED.value,
        }:
            allowed |= {
                CalendarChangeStatus.DRAFT.value,
                CalendarChangeStatus.PENDING_REVIEW.value,
            }
        if row.status not in allowed:
            raise CalendarChangeError(
                "invalid_status",
                f"Cannot apply from {row.status}",
            )

        day = self._repo.get_day(
            exchange_code=row.exchange_code,
            calendar_date=row.market_date,
        )
        before = day_snapshot(day)
        current_rev = int(
            (before or {}).get("revision")
            or (getattr(day, "revision", 1) if day else 0)
            or 0
        )
        if (
            row.expected_revision is not None
            and day is not None
            and current_rev != int(row.expected_revision)
        ):
            raise CalendarChangeError(
                "revision_conflict",
                f"Expected revision {row.expected_revision}, "
                f"current {current_rev}",
            )

        merged = self._merge_values(
            change_type=row.change_type,
            current=before,
            requested=row.requested_values,
        )
        self._validate_values(
            change_type=row.change_type,
            values=merged,
            current=before,
        )

        new_rev = current_rev + 1 if day is not None else 1
        now = datetime.now(timezone.utc)

        # upsert_days는 내부 commit 하므로 여기서는 flush만 사용
        if day is None:
            day = TradingCalendarDay(
                exchange_code=row.exchange_code,
                calendar_date=row.market_date,
                is_trading_day=bool(merged.get("is_trading_day", True)),
                session_type=str(
                    merged.get(
                        "session_type",
                        CalendarSessionType.REGULAR.value,
                    )
                ),
                holiday_name=merged.get("holiday_name"),
                closure_reason=merged.get("closure_reason"),
                regular_open_at=_parse_time(merged.get("regular_open_at")),
                regular_close_at=_parse_time(
                    merged.get("regular_close_at")
                ),
                preopen_at=_parse_time(merged.get("preopen_at")),
                source_type=row.source_type,
                source_code=(row.source_type or "ADMIN_MANUAL")[:30],
                source_reference=row.source_reference,
                verified_status=str(
                    merged.get(
                        "verified_status",
                        CalendarVerifiedStatus.VERIFIED.value,
                    )
                ),
                verified_by=actor,
                verified_at=now,
                timezone="Asia/Seoul",
                revision=1,
            )
            self._session.add(day)
            self._session.flush()
            new_rev = 1
        else:
            day.is_trading_day = bool(merged.get("is_trading_day", True))
            day.session_type = str(
                merged.get("session_type", day.session_type)
            )
            day.holiday_name = merged.get("holiday_name")
            day.closure_reason = merged.get("closure_reason")
            day.regular_open_at = _parse_time(
                merged.get("regular_open_at")
            )
            day.regular_close_at = _parse_time(
                merged.get("regular_close_at")
            )
            if "preopen_at" in merged:
                day.preopen_at = _parse_time(merged.get("preopen_at"))
            day.source_type = row.source_type
            day.source_code = (row.source_type or day.source_code)[:30]
            day.source_reference = row.source_reference
            day.verified_status = str(
                merged.get(
                    "verified_status",
                    CalendarVerifiedStatus.VERIFIED.value,
                )
            )
            day.verified_by = actor
            day.verified_at = now
            day.revision = new_rev
        day.active_change_request_id = int(row.change_request_id)
        day.last_changed_at = now
        day.updated_at = now

        after = day_snapshot(day)
        hist = TradingCalendarDayHistory(
            exchange_code=row.exchange_code,
            calendar_date=row.market_date,
            revision=new_rev,
            change_request_id=int(row.change_request_id),
            before_snapshot=before,
            after_snapshot=after or {},
            reason=row.reason,
            source_type=row.source_type,
            emergency=bool(row.emergency),
            applied_by=actor,
            applied_at=now,
        )
        self._session.add(hist)

        row.status = CalendarChangeStatus.APPLIED.value
        row.applied_by = actor
        row.applied_at = now
        row.applied_revision = new_rev
        row.updated_at = now

        # 동일 날짜의 다른 PENDING을 SUPERSEDED
        self._supersede_peers(row)

        # Cache invalidate + scheduler recompute
        sched_ok = True
        sched_err = None
        try:
            from stock_platform.operation.calendar_cache import (
                invalidate_calendar_cache,
            )
            from stock_platform.operation.session_timeline import (
                invalidate_timeline_cache,
            )

            invalidate_calendar_cache(
                exchange_code=row.exchange_code,
                calendar_date=row.market_date,
            )
            invalidate_timeline_cache(
                exchange_code=row.exchange_code,
                market_date=row.market_date,
            )
            from stock_platform.operation.calendar_scheduler_recompute import (
                recompute_krx_session_jobs,
            )

            # STEP 8-5-15 — Calendar 변경과 Job 영속화를 동일 트랜잭션으로 묶는다.
            recompute_krx_session_jobs(
                exchange_code=row.exchange_code,
                market_date=row.market_date,
                revision=new_rev,
                session_snapshot=after or {},
                session=self._session,
            )
            row.scheduler_recompute_status = "OK"
        except Exception as exc:  # noqa: BLE001
            sched_ok = False
            sched_err = str(exc)[:400]
            row.scheduler_recompute_status = "FAILED"
            row.scheduler_recompute_error = sched_err
            row.status = (
                CalendarChangeStatus.APPLIED_WITH_SCHEDULER_ERROR.value
            )

        audit_calendar_event(
            (
                "CALENDAR_CHANGE_EMERGENCY_APPLIED"
                if row.emergency
                else "CALENDAR_CHANGE_REQUEST_APPLIED"
            ),
            actor=actor,
            detail={
                "change_request_id": int(row.change_request_id),
                "exchange_code": row.exchange_code,
                "market_date": row.market_date.isoformat(),
                "previous_revision": current_rev,
                "new_revision": new_rev,
                "emergency": bool(row.emergency),
                "scheduler_ok": sched_ok,
                "change_type": row.change_type,
            },
        )
        self._session.flush()
        return row

    def create_rollback_request(
        self,
        *,
        exchange_code: str,
        market_date: date,
        target_revision: int,
        reason: str,
        requested_by: str,
    ) -> TradingCalendarChangeRequest:
        hist = self._session.scalar(
            select(TradingCalendarDayHistory).where(
                TradingCalendarDayHistory.exchange_code
                == exchange_code.upper(),
                TradingCalendarDayHistory.calendar_date == market_date,
                TradingCalendarDayHistory.revision == int(target_revision),
            )
        )
        if hist is None:
            raise CalendarChangeError(
                "history_not_found",
                f"No history for revision {target_revision}",
            )
        snap = dict(hist.after_snapshot or {})
        return self.create_request(
            exchange_code=exchange_code,
            market_date=market_date,
            change_type=CalendarChangeType.ROLLBACK.value,
            requested_values=snap,
            reason=reason,
            source_type=CalendarSourceType.ADMIN_MANUAL.value,
            requested_by=requested_by,
            source_reference=f"rollback:rev:{target_revision}",
            expected_revision=None,
            rollback_of_request_id=hist.change_request_id,
        )

    def list_requests(
        self,
        *,
        status: str | None = None,
        exchange_code: str = "KRX",
        limit: int = 100,
    ) -> list[TradingCalendarChangeRequest]:
        stmt = select(TradingCalendarChangeRequest).where(
            TradingCalendarChangeRequest.exchange_code
            == exchange_code.upper()
        )
        if status:
            stmt = stmt.where(
                TradingCalendarChangeRequest.status == status
            )
        stmt = stmt.order_by(
            TradingCalendarChangeRequest.requested_at.desc()
        ).limit(limit)
        return list(self._session.scalars(stmt))

    def get_request(
        self, request_id: int
    ) -> TradingCalendarChangeRequest | None:
        return self._session.get(
            TradingCalendarChangeRequest, int(request_id)
        )

    def list_history(
        self, *, exchange_code: str, market_date: date
    ) -> list[TradingCalendarDayHistory]:
        stmt = (
            select(TradingCalendarDayHistory)
            .where(
                TradingCalendarDayHistory.exchange_code
                == exchange_code.upper(),
                TradingCalendarDayHistory.calendar_date == market_date,
            )
            .order_by(TradingCalendarDayHistory.revision.desc())
        )
        return list(self._session.scalars(stmt))

    def health_summary(self) -> dict[str, Any]:
        from sqlalchemy import func as sa_func

        pending = int(
            self._session.scalar(
                select(sa_func.count()).select_from(
                    TradingCalendarChangeRequest
                ).where(
                    TradingCalendarChangeRequest.status.in_(
                        list(ACTIVE_CHANGE_STATUSES)
                    )
                )
            )
            or 0
        )
        conflicts = int(
            self._session.scalar(
                select(sa_func.count()).select_from(
                    TradingCalendarChangeRequest
                ).where(
                    TradingCalendarChangeRequest.status
                    == CalendarChangeStatus.CONFLICT.value
                )
            )
            or 0
        )
        today = date.today()
        day = self._repo.get_day(exchange_code="KRX", calendar_date=today)
        special = False
        if day and day.session_type in {
            CalendarSessionType.DELAYED_OPEN.value,
            CalendarSessionType.EARLY_CLOSE.value,
            CalendarSessionType.SPECIAL_SESSION.value,
            CalendarSessionType.CLOSED.value,
        }:
            special = True
        return {
            "pending_change_requests": pending,
            "conflict_change_requests": conflicts,
            "today_special_session": special,
            "today_session_type": (
                day.session_type if day else None
            ),
            "today_revision": (
                int(getattr(day, "revision", 0) or 0) if day else None
            ),
        }

    def _require(self, request_id: int) -> TradingCalendarChangeRequest:
        row = self.get_request(request_id)
        if row is None:
            raise CalendarChangeError(
                "not_found", f"Request {request_id} not found"
            )
        return row

    def _detect_conflict(
        self,
        *,
        exchange_code: str,
        market_date: date,
        change_type: str,
        exclude_id: int | None = None,
    ) -> str | None:
        stmt = select(TradingCalendarChangeRequest).where(
            TradingCalendarChangeRequest.exchange_code == exchange_code,
            TradingCalendarChangeRequest.market_date == market_date,
            TradingCalendarChangeRequest.status.in_(
                list(ACTIVE_CHANGE_STATUSES)
            ),
        )
        rows = list(self._session.scalars(stmt))
        for other in rows:
            if exclude_id and int(other.change_request_id) == exclude_id:
                continue
            if other.status not in ACTIVE_CHANGE_STATUSES:
                continue
            # FULL_DAY_CLOSE vs open-type
            if (
                change_type == CalendarChangeType.FULL_DAY_CLOSE.value
                and other.change_type
                in {
                    CalendarChangeType.DELAYED_OPEN.value,
                    CalendarChangeType.EARLY_CLOSE.value,
                    CalendarChangeType.SPECIAL_SESSION.value,
                    CalendarChangeType.OPEN_DAY_OVERRIDE.value,
                }
            ):
                return (
                    f"Conflicts with pending "
                    f"{other.change_type}#{other.change_request_id}"
                )
            if (
                other.change_type
                == CalendarChangeType.FULL_DAY_CLOSE.value
                and change_type
                != CalendarChangeType.FULL_DAY_CLOSE.value
            ):
                return (
                    f"Conflicts with pending FULL_DAY_CLOSE"
                    f"#{other.change_request_id}"
                )
            if other.change_type == change_type:
                return (
                    f"Duplicate pending {change_type}"
                    f"#{other.change_request_id}"
                )
        return None

    def _validate_values(
        self,
        *,
        change_type: str,
        values: dict[str, Any],
        current: dict[str, Any] | None,
    ) -> None:
        _ = current
        is_trading = values.get("is_trading_day")
        session = values.get("session_type")
        open_t = _parse_time(values.get("regular_open_at"))
        close_t = _parse_time(values.get("regular_close_at"))

        if change_type == CalendarChangeType.FULL_DAY_CLOSE.value:
            if is_trading is True:
                raise CalendarChangeError(
                    "invalid_values",
                    "FULL_DAY_CLOSE requires is_trading_day=false",
                )
            values["is_trading_day"] = False
            values["session_type"] = CalendarSessionType.CLOSED.value
            if not values.get("closure_reason"):
                raise CalendarChangeError(
                    "closure_reason_required",
                    "closure_reason required for full-day close",
                )
            values.setdefault(
                "verified_status",
                CalendarVerifiedStatus.VERIFIED.value,
            )
            return

        if change_type == CalendarChangeType.DELAYED_OPEN.value:
            values["is_trading_day"] = True
            values["session_type"] = (
                CalendarSessionType.DELAYED_OPEN.value
            )
        elif change_type == CalendarChangeType.EARLY_CLOSE.value:
            values["is_trading_day"] = True
            values["session_type"] = (
                CalendarSessionType.EARLY_CLOSE.value
            )
        elif change_type == CalendarChangeType.SPECIAL_SESSION.value:
            values["is_trading_day"] = True
            values["session_type"] = (
                CalendarSessionType.SPECIAL_SESSION.value
            )

        session = values.get("session_type") or session
        is_trading = values.get("is_trading_day", True)
        if is_trading is False and open_t and close_t:
            raise CalendarChangeError(
                "invalid_values",
                "Closed day cannot have open/close times",
            )
        if (
            session == CalendarSessionType.CLOSED.value
            and is_trading is True
        ):
            raise CalendarChangeError(
                "invalid_values",
                "CLOSED session cannot be trading day",
            )
        if open_t and close_t and close_t <= open_t:
            raise CalendarChangeError(
                "invalid_session_times",
                "regular_close_at must be after regular_open_at",
            )
        if change_type in {
            CalendarChangeType.DELAYED_OPEN.value,
            CalendarChangeType.EARLY_CLOSE.value,
            CalendarChangeType.SPECIAL_SESSION.value,
            CalendarChangeType.SESSION_TIME_CHANGE.value,
        }:
            if open_t is None or close_t is None:
                raise CalendarChangeError(
                    "session_times_required",
                    "open and close times required",
                )

    def _merge_values(
        self,
        *,
        change_type: str,
        current: dict[str, Any] | None,
        requested: dict[str, Any],
    ) -> dict[str, Any]:
        base = dict(current or {})
        base.update({k: v for k, v in requested.items() if v is not None})
        # ensure change_type defaults applied
        self._validate_values(
            change_type=change_type, values=base, current=current
        )
        return base

    def _supersede_peers(
        self, applied: TradingCalendarChangeRequest
    ) -> None:
        stmt = select(TradingCalendarChangeRequest).where(
            TradingCalendarChangeRequest.exchange_code
            == applied.exchange_code,
            TradingCalendarChangeRequest.market_date
            == applied.market_date,
            TradingCalendarChangeRequest.status.in_(
                list(ACTIVE_CHANGE_STATUSES)
            ),
            TradingCalendarChangeRequest.change_request_id
            != applied.change_request_id,
        )
        for other in self._session.scalars(stmt):
            if int(other.change_request_id) == int(
                applied.change_request_id
            ):
                continue
            if other.status not in ACTIVE_CHANGE_STATUSES:
                continue
            other.status = CalendarChangeStatus.SUPERSEDED.value
            other.supersedes_request_id = int(
                applied.change_request_id
            )


def request_as_dict(row: TradingCalendarChangeRequest) -> dict[str, Any]:
    return {
        "change_request_id": int(row.change_request_id),
        "exchange_code": row.exchange_code,
        "market_date": row.market_date.isoformat(),
        "change_type": row.change_type,
        "requested_values": row.requested_values,
        "current_values": row.current_values,
        "reason": row.reason,
        "source_type": row.source_type,
        "source_reference": row.source_reference,
        "emergency": bool(row.emergency),
        "status": row.status,
        "conflict_message": row.conflict_message,
        "expected_revision": row.expected_revision,
        "applied_revision": row.applied_revision,
        "requested_by": row.requested_by,
        "requested_at": (
            row.requested_at.isoformat() if row.requested_at else None
        ),
        "reviewed_by": row.reviewed_by,
        "reviewed_at": (
            row.reviewed_at.isoformat() if row.reviewed_at else None
        ),
        "review_comment": row.review_comment,
        "applied_by": row.applied_by,
        "applied_at": (
            row.applied_at.isoformat() if row.applied_at else None
        ),
        "rejected_reason": row.rejected_reason,
        "scheduler_recompute_status": row.scheduler_recompute_status,
        "scheduler_recompute_error": row.scheduler_recompute_error,
    }
