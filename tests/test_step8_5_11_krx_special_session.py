"""STEP 8-5-11 — KRX Special Session / Change Request tests."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from stock_platform.operation.calendar_cache import (
    cache_get,
    cache_set,
    invalidate_calendar_cache,
)
from stock_platform.operation.calendar_change_constants import (
    CalendarChangeStatus,
    CalendarChangeType,
    CalendarSourceType,
)
from stock_platform.operation.calendar_change_service import (
    CalendarChangeError,
    TradingCalendarChangeService,
)
from stock_platform.operation.calendar_constants import (
    CalendarSessionType,
    CalendarVerifiedStatus,
)
from stock_platform.operation.calendar_scheduler_recompute import (
    build_job_id,
    recompute_krx_session_jobs,
)
from stock_platform.operation.calendar_service import TradingCalendarService
from tests.migration_helpers import (
    alembic_current_head,
    assert_revision_exists,
)


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    def __init__(self):
        self.added: list = []
        self._next_id = 1

    def add(self, obj) -> None:
        if getattr(obj, "change_request_id", None) in (None, 0):
            if hasattr(obj, "change_request_id"):
                obj.change_request_id = self._next_id
                self._next_id += 1
        if getattr(obj, "history_id", None) in (None, 0):
            if hasattr(obj, "history_id"):
                obj.history_id = self._next_id
                self._next_id += 1
        if getattr(obj, "calendar_day_id", None) in (None, 0):
            if hasattr(obj, "calendar_day_id"):
                obj.calendar_day_id = self._next_id
                self._next_id += 1
        self.added.append(obj)

    def flush(self) -> None:
        return None

    def get(self, cls, ident):
        for obj in self.added:
            if isinstance(obj, cls) and getattr(
                obj, "change_request_id", None
            ) == ident:
                return obj
        return None

    def scalar(self, _stmt):
        return None

    def scalars(self, _stmt):
        from stock_platform.operation.calendar_change_entities import (
            TradingCalendarChangeRequest,
        )

        rows = [
            o
            for o in self.added
            if isinstance(o, TradingCalendarChangeRequest)
        ]
        return _FakeScalars(rows)


def _open_day(d: date, *, revision: int = 1, **kwargs):
    base = dict(
        exchange_code="KRX",
        calendar_date=d,
        is_trading_day=True,
        holiday_name=None,
        closure_reason=None,
        source_code="GENERATED_WEEKDAY",
        source_type="GENERATED_WEEKDAY",
        source_reference=None,
        session_type=CalendarSessionType.REGULAR.value,
        verified_status=CalendarVerifiedStatus.VERIFIED.value,
        regular_open_at=time(9, 0),
        regular_close_at=time(15, 30),
        preopen_at=time(8, 30),
        timezone="Asia/Seoul",
        revision=revision,
        verified_by="tester",
        verified_at=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


class FakeRepo:
    def __init__(self, rows=None):
        self.rows = rows or {}

    def get_day(self, *, exchange_code, calendar_date):
        return self.rows.get((exchange_code.upper(), calendar_date))


def test_step8_5_11_revision_in_chain() -> None:
    assert_revision_exists("z3d4e5f6a7b8")
    head = alembic_current_head()
    assert head
    assert_revision_exists(head)


def test_change_enums_stable() -> None:
    assert CalendarChangeStatus.APPLIED.value == "APPLIED"
    assert (
        CalendarChangeStatus.APPLIED_WITH_SCHEDULER_ERROR.value
        == "APPLIED_WITH_SCHEDULER_ERROR"
    )
    assert CalendarChangeType.DELAYED_OPEN.value == "DELAYED_OPEN"
    assert CalendarSourceType.EMERGENCY_ADMIN.value == "EMERGENCY_ADMIN"


def test_create_draft_and_submit_approve_apply_idempotent() -> None:
    session = FakeSession()
    svc = TradingCalendarChangeService(session)
    d = date(2026, 11, 19)
    day = _open_day(d, revision=3)
    svc._repo = FakeRepo({("KRX", d): day})  # type: ignore[assignment]

    req = svc.create_request(
        exchange_code="KRX",
        market_date=d,
        change_type=CalendarChangeType.DELAYED_OPEN.value,
        requested_values={
            "regular_open_at": "10:00:00",
            "regular_close_at": "16:30:00",
        },
        reason="수능일 지연 개장",
        source_type=CalendarSourceType.KRX_OFFICIAL_NOTICE.value,
        source_reference="KRX-NOTICE-CSAT-2026",
        requested_by="admin1",
        expected_revision=3,
    )
    assert req.status == CalendarChangeStatus.DRAFT.value
    assert req.expected_revision == 3

    svc.submit(int(req.change_request_id), actor="admin1")
    assert req.status == CalendarChangeStatus.PENDING_REVIEW.value

    svc.approve(int(req.change_request_id), actor="admin2")
    assert req.status == CalendarChangeStatus.APPROVED.value
    assert req.reviewed_by == "admin2"

    applied = svc.apply(int(req.change_request_id), actor="admin2")
    assert applied.status in {
        CalendarChangeStatus.APPLIED.value,
        CalendarChangeStatus.APPLIED_WITH_SCHEDULER_ERROR.value,
    }
    assert day.revision == 4
    assert day.session_type == CalendarSessionType.DELAYED_OPEN.value
    assert day.regular_open_at == time(10, 0)
    assert day.regular_close_at == time(16, 30)

    again = svc.apply(int(req.change_request_id), actor="admin2")
    assert again.applied_revision == applied.applied_revision


def test_same_approver_policy() -> None:
    session = FakeSession()
    svc = TradingCalendarChangeService(
        session, require_separate_approver=True
    )
    d = date(2026, 12, 24)
    svc._repo = FakeRepo({("KRX", d): _open_day(d)})  # type: ignore[assignment]
    req = svc.create_request(
        exchange_code="KRX",
        market_date=d,
        change_type=CalendarChangeType.EARLY_CLOSE.value,
        requested_values={
            "regular_open_at": "09:00:00",
            "regular_close_at": "14:30:00",
        },
        reason="연말 조기 종료",
        source_type=CalendarSourceType.ADMIN_MANUAL.value,
        source_reference="ops-note-1",
        requested_by="admin1",
    )
    svc.submit(int(req.change_request_id), actor="admin1")
    with pytest.raises(CalendarChangeError) as exc:
        svc.approve(int(req.change_request_id), actor="admin1")
    assert exc.value.code == "same_approver_forbidden"


def test_full_day_close_requires_closure_reason() -> None:
    session = FakeSession()
    svc = TradingCalendarChangeService(session)
    d = date(2026, 10, 1)
    svc._repo = FakeRepo({("KRX", d): _open_day(d)})  # type: ignore[assignment]
    with pytest.raises(CalendarChangeError) as exc:
        svc.create_request(
            exchange_code="KRX",
            market_date=d,
            change_type=CalendarChangeType.FULL_DAY_CLOSE.value,
            requested_values={"is_trading_day": False},
            reason="임시휴장",
            source_type=CalendarSourceType.GOVERNMENT_NOTICE.value,
            source_reference="gov-1",
            requested_by="admin1",
        )
    assert exc.value.code == "closure_reason_required"


def test_close_before_open_rejected() -> None:
    session = FakeSession()
    svc = TradingCalendarChangeService(session)
    d = date(2026, 9, 1)
    svc._repo = FakeRepo({("KRX", d): _open_day(d)})  # type: ignore[assignment]
    with pytest.raises(CalendarChangeError) as exc:
        svc.create_request(
            exchange_code="KRX",
            market_date=d,
            change_type=CalendarChangeType.SESSION_TIME_CHANGE.value,
            requested_values={
                "regular_open_at": "15:00:00",
                "regular_close_at": "09:00:00",
            },
            reason="잘못된 시간",
            source_type=CalendarSourceType.ADMIN_MANUAL.value,
            source_reference="bad",
            requested_by="admin1",
        )
    assert exc.value.code == "invalid_session_times"


def test_revision_conflict_blocks_stale_apply() -> None:
    session = FakeSession()
    svc = TradingCalendarChangeService(session)
    d = date(2026, 8, 10)
    day = _open_day(d, revision=5)
    svc._repo = FakeRepo({("KRX", d): day})  # type: ignore[assignment]
    req = svc.create_request(
        exchange_code="KRX",
        market_date=d,
        change_type=CalendarChangeType.EARLY_CLOSE.value,
        requested_values={
            "regular_open_at": "09:00:00",
            "regular_close_at": "14:00:00",
        },
        reason="조기종료",
        source_type=CalendarSourceType.ADMIN_MANUAL.value,
        source_reference="r1",
        requested_by="admin1",
        expected_revision=5,
        emergency=True,
    )
    day.revision = 6  # 다른 변경이 먼저 적용됨
    with pytest.raises(CalendarChangeError) as exc:
        svc.apply(int(req.change_request_id), actor="admin1")
    assert exc.value.code == "revision_conflict"


def test_emergency_requires_source_reference() -> None:
    session = FakeSession()
    svc = TradingCalendarChangeService(session)
    d = date(2026, 7, 22)
    svc._repo = FakeRepo({("KRX", d): _open_day(d)})  # type: ignore[assignment]
    with pytest.raises(CalendarChangeError) as exc:
        svc.create_request(
            exchange_code="KRX",
            market_date=d,
            change_type=CalendarChangeType.FULL_DAY_CLOSE.value,
            requested_values={
                "is_trading_day": False,
                "closure_reason": "긴급 휴장",
            },
            reason="긴급 휴장",
            source_type=CalendarSourceType.EMERGENCY_ADMIN.value,
            emergency=True,
            requested_by="admin1",
        )
    assert exc.value.code == "source_required"


def test_temporary_close_blocks_orders() -> None:
    d = date(2026, 7, 22)
    closed = _open_day(
        d,
        is_trading_day=False,
        session_type=CalendarSessionType.CLOSED.value,
        closure_reason="임시휴장",
        regular_open_at=None,
        regular_close_at=None,
    )
    svc = TradingCalendarService(FakeRepo({("KRX", d): closed}))  # type: ignore[arg-type]
    moment = datetime(2026, 7, 22, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    with pytest.raises(ValueError, match="market closed|KRX"):
        svc.require_live_order_session(exchange_code="KRX", moment=moment)


def test_delayed_open_blocks_before_open() -> None:
    d = date(2026, 11, 19)
    delayed = _open_day(
        d,
        session_type=CalendarSessionType.DELAYED_OPEN.value,
        regular_open_at=time(10, 0),
        regular_close_at=time(16, 30),
    )
    svc = TradingCalendarService(FakeRepo({("KRX", d): delayed}))  # type: ignore[arg-type]
    early = datetime(2026, 11, 19, 9, 15, tzinfo=ZoneInfo("Asia/Seoul"))
    with pytest.raises(ValueError, match="outside regular session"):
        svc.require_live_order_session(exchange_code="KRX", moment=early)
    ok = datetime(2026, 11, 19, 10, 30, tzinfo=ZoneInfo("Asia/Seoul"))
    decision = svc.require_live_order_session(
        exchange_code="KRX", moment=ok
    )
    assert decision.live_allowed is True


def test_user_status_special_messages() -> None:
    d = date.today()
    # 주말이면 다음 평일로 고정 테스트가 깨질 수 있어 Fake evaluate 경로 사용
    delayed = _open_day(
        d,
        session_type=CalendarSessionType.DELAYED_OPEN.value,
        regular_open_at=time(10, 0),
        regular_close_at=time(16, 30),
    )
    svc = TradingCalendarService(FakeRepo({("KRX", d): delayed}))  # type: ignore[arg-type]
    # next_trading_day 탐색이 실패할 수 있어 monkeypatch
    svc.next_trading_day = lambda **kwargs: d + timedelta(days=1)  # type: ignore[method-assign]
    status = svc.user_status("KRX")
    assert status["is_special_session"] is True
    assert "10:00" in status["status_message"]


def test_calendar_cache_revision_invalidate() -> None:
    invalidate_calendar_cache()
    d = date(2026, 7, 22)
    cache_set(
        exchange_code="KRX",
        calendar_date=d,
        revision=1,
        payload={"ok": True},
        ttl_seconds=30,
    )
    hit = cache_get(exchange_code="KRX", calendar_date=d, ttl_seconds=30)
    assert hit is not None
    assert hit[0] == 1
    invalidate_calendar_cache(exchange_code="KRX", calendar_date=d)
    assert (
        cache_get(exchange_code="KRX", calendar_date=d, ttl_seconds=30)
        is None
    )


def test_dynamic_job_key_and_past_skip() -> None:
    d = date(2020, 1, 2)
    jid = build_job_id(
        exchange_code="KRX",
        market_date=d,
        job_type="PREOPEN_RECOVERY",
        revision=2,
    )
    assert jid == "KRX:2020-01-02:PREOPEN_RECOVERY:rev2"
    out = recompute_krx_session_jobs(
        exchange_code="KRX",
        market_date=d,
        revision=2,
        session_snapshot={
            "is_trading_day": True,
            "session_type": "REGULAR",
            "regular_open_at": "09:00:00",
            "regular_close_at": "15:30:00",
        },
    )
    assert out["status"] == "SKIPPED_PAST"


def test_conflict_duplicate_pending() -> None:
    session = FakeSession()
    svc = TradingCalendarChangeService(session)
    d = date(2026, 6, 15)
    svc._repo = FakeRepo({("KRX", d): _open_day(d)})  # type: ignore[assignment]
    first = svc.create_request(
        exchange_code="KRX",
        market_date=d,
        change_type=CalendarChangeType.DELAYED_OPEN.value,
        requested_values={
            "regular_open_at": "10:00:00",
            "regular_close_at": "16:30:00",
        },
        reason="수능일 지연 개장 공지",
        source_type=CalendarSourceType.ADMIN_MANUAL.value,
        source_reference="a",
        requested_by="admin1",
    )
    assert first.status == CalendarChangeStatus.DRAFT.value
    second = svc.create_request(
        exchange_code="KRX",
        market_date=d,
        change_type=CalendarChangeType.DELAYED_OPEN.value,
        requested_values={
            "regular_open_at": "10:30:00",
            "regular_close_at": "17:00:00",
        },
        reason="수능일 시각 정정",
        source_type=CalendarSourceType.ADMIN_MANUAL.value,
        source_reference="b",
        requested_by="admin1",
    )
    assert second.status == CalendarChangeStatus.CONFLICT.value
