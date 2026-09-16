"""STEP 8-5-13 — KRX Trading Session Timeline / Phase 테스트.

Migration 없음 — SessionOffsetConfig/설정 필드는 메모리·Settings 로만
동작하므로 별도 Alembic Revision이 필요하지 않는다. (단일 head만 검증)
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from stock_platform.operation.calendar_constants import (
    CalendarReasonCode,
    CalendarSessionType,
    KRX_TIMEZONE,
)
from stock_platform.operation.session_timeline import (
    SessionOffsetConfig,
    SessionTimelineReasonCode,
    TradingSessionPhase,
    TradingSessionTimelineResolver,
    invalidate_timeline_cache,
    krx_cron_fallback_timing,
    phase_reason_code,
)
from tests.migration_helpers import alembic_current_head

TZ = ZoneInfo(KRX_TIMEZONE)

# 오프셋 기본값과 동일 — Preopen 30분, Cutoff 10분,
# Postclose 10분, Snapshot 10분, Settlement 20분, AI 30분
OFFSETS = SessionOffsetConfig()


def _resolver() -> TradingSessionTimelineResolver:
    return TradingSessionTimelineResolver(offsets=OFFSETS)


def _at(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=TZ)


class _FixedDateTime(datetime):
    """`safety_guard`가 사용하는 `datetime.now()`를 고정하기 위한 테스트용 대체 클래스."""

    _fixed: datetime | None = None

    @classmethod
    def now(cls, tz=None):  # noqa: D102
        if cls._fixed is None:
            return super().now(tz)
        if tz is None:
            return cls._fixed
        return cls._fixed.astimezone(tz)


def _patch_safety_guard_now(local_moment: datetime):
    """`safety_guard` 모듈 내 `datetime.now(timezone.utc)` 호출을 고정 시각으로 패치."""

    _FixedDateTime._fixed = local_moment.astimezone(timezone.utc)
    return patch(
        "stock_platform.realtime.safety_guard.datetime", _FixedDateTime
    )


def test_alembic_single_head() -> None:
    """STEP 8-5-13은 Migration 없음 — 단일 head만 확인."""

    head = alembic_current_head()
    assert head


# ---------------------------------------------------------------------------
# Resolver — 정규장 / 지연개장 / 조기종료 / 휴장 / Calendar 누락
# ---------------------------------------------------------------------------


def test_resolver_regular_day_offsets() -> None:
    d = date(2026, 8, 3)  # 월요일
    timeline = _resolver().resolve_from_decision(
        exchange_code="KRX",
        market_date=d,
        is_trading_day=True,
        live_allowed=True,
        reason_code=CalendarReasonCode.CALENDAR_OPEN.value,
        session_type=CalendarSessionType.REGULAR.value,
        regular_open_at=time(9, 0),
        regular_close_at=time(15, 30),
        revision=1,
    )
    assert timeline.preopen_start_at == _at(d, time(8, 30))
    assert timeline.regular_open_at == _at(d, time(9, 0))
    assert timeline.new_entry_cutoff_at == _at(d, time(15, 20))
    assert timeline.regular_close_at == _at(d, time(15, 30))
    assert timeline.recovery_preopen_at == _at(d, time(8, 30))
    assert timeline.recovery_postclose_at == _at(d, time(15, 40))
    assert timeline.snapshot_at == _at(d, time(15, 40))
    assert timeline.settlement_at == _at(d, time(15, 50))
    assert timeline.analysis_at == _at(d, time(16, 0))


def test_resolver_delayed_open_day() -> None:
    d = date(2026, 11, 19)  # 수능일 지연개장 가정
    timeline = _resolver().resolve_from_decision(
        exchange_code="KRX",
        market_date=d,
        is_trading_day=True,
        live_allowed=True,
        reason_code=CalendarReasonCode.CALENDAR_OPEN.value,
        session_type=CalendarSessionType.DELAYED_OPEN.value,
        regular_open_at=time(10, 0),
        regular_close_at=time(16, 30),
        revision=2,
    )
    assert timeline.regular_open_at == _at(d, time(10, 0))
    assert timeline.regular_close_at == _at(d, time(16, 30))
    assert timeline.preopen_start_at == _at(d, time(9, 30))
    # 09:15 — 아직 Preopen 이전(장 시작 30분 전보다 이전)
    assert timeline.phase_at(_at(d, time(9, 15))) == (
        TradingSessionPhase.PREOPEN
    )
    # 10:30 — OPEN
    assert timeline.phase_at(_at(d, time(10, 30))) == (
        TradingSessionPhase.OPEN
    )


def test_resolver_early_close_day() -> None:
    d = date(2026, 12, 31)  # 연말 조기종료 가정
    timeline = _resolver().resolve_from_decision(
        exchange_code="KRX",
        market_date=d,
        is_trading_day=True,
        live_allowed=True,
        reason_code=CalendarReasonCode.CALENDAR_OPEN.value,
        session_type=CalendarSessionType.EARLY_CLOSE.value,
        regular_open_at=time(9, 0),
        regular_close_at=time(14, 30),
        revision=3,
    )
    assert timeline.regular_close_at == _at(d, time(14, 30))
    assert timeline.new_entry_cutoff_at == _at(d, time(14, 20))
    # 14:25 — Cutoff 이후, Close 이전 → EXIT_ONLY
    assert timeline.phase_at(_at(d, time(14, 25))) == (
        TradingSessionPhase.EXIT_ONLY
    )
    # 14:35 — Close 이후 → CLOSED
    assert timeline.phase_at(_at(d, time(14, 35))) == (
        TradingSessionPhase.CLOSED
    )


def test_resolver_holiday_non_trading_day() -> None:
    d = date(2026, 1, 1)
    timeline = _resolver().resolve_from_decision(
        exchange_code="KRX",
        market_date=d,
        is_trading_day=False,
        live_allowed=False,
        reason_code=CalendarReasonCode.CALENDAR_CLOSED.value,
        session_type=CalendarSessionType.CLOSED.value,
        regular_open_at=None,
        regular_close_at=None,
        revision=1,
    )
    assert timeline.phase_at(_at(d, time(11, 0))) == (
        TradingSessionPhase.NON_TRADING_DAY
    )
    assert timeline.regular_open_at is None
    assert timeline.recovery_preopen_at is None


def test_resolver_missing_calendar_is_unavailable_not_non_trading() -> None:
    """Calendar 자체가 없는 상태는 '휴장'과 달리 Fail Closed 대상이다."""

    d = date(2026, 3, 2)
    timeline = _resolver().resolve_from_decision(
        exchange_code="KRX",
        market_date=d,
        is_trading_day=False,
        live_allowed=False,
        reason_code=CalendarReasonCode.CALENDAR_MISSING.value,
        session_type=None,
        regular_open_at=None,
        regular_close_at=None,
        revision=0,
    )
    assert timeline.phase_at(_at(d, time(11, 0))) == (
        TradingSessionPhase.CALENDAR_UNAVAILABLE
    )


def test_resolver_stale_calendar_is_unavailable() -> None:
    d = date(2026, 3, 3)
    timeline = _resolver().resolve_from_decision(
        exchange_code="KRX",
        market_date=d,
        is_trading_day=False,
        live_allowed=False,
        reason_code=CalendarReasonCode.CALENDAR_STALE.value,
        session_type=None,
        regular_open_at=None,
        regular_close_at=None,
        revision=5,
    )
    assert timeline.phase_at(_at(d, time(11, 0))) == (
        TradingSessionPhase.CALENDAR_UNAVAILABLE
    )


# ---------------------------------------------------------------------------
# Phase 경계
# ---------------------------------------------------------------------------


def _regular_timeline(d: date, revision: int = 1):
    return _resolver().resolve_from_decision(
        exchange_code="KRX",
        market_date=d,
        is_trading_day=True,
        live_allowed=True,
        reason_code=CalendarReasonCode.CALENDAR_OPEN.value,
        session_type=CalendarSessionType.REGULAR.value,
        regular_open_at=time(9, 0),
        regular_close_at=time(15, 30),
        revision=revision,
    )


def test_phase_boundaries_regular_day() -> None:
    d = date(2026, 8, 4)
    timeline = _regular_timeline(d)

    cases = [
        (time(8, 0), TradingSessionPhase.PREOPEN),
        (time(8, 30), TradingSessionPhase.PREOPEN),
        (time(8, 59, 59), TradingSessionPhase.PREOPEN),
        (time(9, 0), TradingSessionPhase.OPEN),
        (time(12, 0), TradingSessionPhase.OPEN),
        (time(15, 19, 59), TradingSessionPhase.OPEN),
        (time(15, 20), TradingSessionPhase.EXIT_ONLY),
        (time(15, 29, 59), TradingSessionPhase.EXIT_ONLY),
        (time(15, 30), TradingSessionPhase.CLOSED),
        (time(15, 39, 59), TradingSessionPhase.CLOSED),
        (time(15, 40), TradingSessionPhase.POST_CLOSE),
        (time(23, 0), TradingSessionPhase.POST_CLOSE),
    ]
    for t, expected in cases:
        assert timeline.phase_at(_at(d, t)) == expected, (
            f"{t} expected {expected}"
        )


def test_allows_new_entry_and_risk_reducing() -> None:
    d = date(2026, 8, 5)
    timeline = _regular_timeline(d)

    open_moment = _at(d, time(10, 0))
    exit_only_moment = _at(d, time(15, 25))
    closed_moment = _at(d, time(16, 0))

    assert timeline.allows_new_entry(open_moment) is True
    assert timeline.allows_new_entry(exit_only_moment) is False
    assert timeline.allows_risk_reducing(open_moment) is True
    assert timeline.allows_risk_reducing(exit_only_moment) is True
    assert timeline.allows_risk_reducing(closed_moment) is False

    assert (
        timeline.allows_any_order(exit_only_moment, is_risk_reducing=True)
        is True
    )
    assert (
        timeline.allows_any_order(exit_only_moment, is_risk_reducing=False)
        is False
    )


def test_next_transition() -> None:
    d = date(2026, 8, 6)
    timeline = _regular_timeline(d)

    at_open, phase_open = timeline.next_transition(_at(d, time(8, 45)))
    assert at_open == _at(d, time(9, 0))
    assert phase_open == TradingSessionPhase.OPEN

    at_exit, phase_exit = timeline.next_transition(_at(d, time(10, 0)))
    assert at_exit == _at(d, time(15, 20))
    assert phase_exit == TradingSessionPhase.EXIT_ONLY

    at_none, phase_none = timeline.next_transition(_at(d, time(23, 0)))
    assert at_none is None
    assert phase_none is None


def test_phase_reason_code_mapping_complete() -> None:
    for phase in TradingSessionPhase:
        # 매핑 누락 시 KeyError로 실패
        assert isinstance(phase_reason_code(phase), str)
    assert (
        phase_reason_code(TradingSessionPhase.EXIT_ONLY)
        == SessionTimelineReasonCode.MARKET_EXIT_ONLY.value
    )


# ---------------------------------------------------------------------------
# TradingTimeRule (Risk Engine) — Session Timeline Phase 연동
# ---------------------------------------------------------------------------


def _order_request(
    *,
    side,
    requested_at: datetime,
    is_risk_reducing: bool = False,
    exchange_code: str = "KRX",
):
    from stock_platform.risk_engine.models import (
        RiskOrderRequest,
        RiskOrderSide,
    )

    return RiskOrderRequest(
        exchange_code=exchange_code,
        symbol="005930",
        side=RiskOrderSide(side),
        quantity=Decimal("1"),
        price=Decimal("70000"),
        account_id=1,
        requested_at=requested_at,
        is_risk_reducing=is_risk_reducing,
    )


def _account_state():
    from stock_platform.risk_engine.models import RiskAccountState

    return RiskAccountState(
        cash_balance=Decimal("1000000"),
        total_asset_value=Decimal("1000000"),
        invested_amount=Decimal("0"),
        daily_realized_profit_loss=Decimal("0"),
        daily_unrealized_profit_loss=Decimal("0"),
        open_position_count=0,
        symbol_position_quantity=Decimal("0"),
    )


def _policy(**overrides):
    from stock_platform.risk_engine.models import RiskPolicy

    return RiskPolicy(**overrides)


def test_trading_time_rule_blocks_buy_outside_open() -> None:
    from stock_platform.risk_engine.models import RiskDecisionLevel
    from stock_platform.risk_engine.rules import TradingTimeRule

    d = date(2026, 8, 7)
    timeline = _regular_timeline(d)
    order = _order_request(side="BUY", requested_at=_at(d, time(15, 25)))

    with patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=timeline,
    ):
        result = TradingTimeRule().evaluate(
            order=order, account=_account_state(), policy=_policy()
        )
    assert result.level == RiskDecisionLevel.BLOCK
    assert result.detail["phase"] == TradingSessionPhase.EXIT_ONLY.value


def test_trading_time_rule_allows_sell_during_exit_only() -> None:
    from stock_platform.risk_engine.models import RiskDecisionLevel
    from stock_platform.risk_engine.rules import TradingTimeRule

    d = date(2026, 8, 10)
    timeline = _regular_timeline(d)
    order = _order_request(side="SELL", requested_at=_at(d, time(15, 25)))

    with patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=timeline,
    ):
        result = TradingTimeRule().evaluate(
            order=order, account=_account_state(), policy=_policy()
        )
    assert result.level == RiskDecisionLevel.PASS
    assert result.detail["phase"] == TradingSessionPhase.EXIT_ONLY.value


def test_trading_time_rule_allows_buy_when_open() -> None:
    from stock_platform.risk_engine.models import RiskDecisionLevel
    from stock_platform.risk_engine.rules import TradingTimeRule

    d = date(2026, 8, 11)
    timeline = _regular_timeline(d)
    order = _order_request(side="BUY", requested_at=_at(d, time(10, 0)))

    with patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=timeline,
    ):
        result = TradingTimeRule().evaluate(
            order=order, account=_account_state(), policy=_policy()
        )
    assert result.level == RiskDecisionLevel.PASS
    assert result.detail["phase"] == TradingSessionPhase.OPEN.value


def test_trading_time_rule_skips_non_krx() -> None:
    from stock_platform.risk_engine.models import RiskDecisionLevel
    from stock_platform.risk_engine.rules import TradingTimeRule

    order = _order_request(
        side="BUY",
        requested_at=datetime(2026, 8, 11, tzinfo=ZoneInfo("UTC")),
        exchange_code="UPBIT",
    )
    result = TradingTimeRule().evaluate(
        order=order, account=_account_state(), policy=_policy()
    )
    assert result.level == RiskDecisionLevel.PASS


# ---------------------------------------------------------------------------
# Realtime Safety Guard — KRX Phase 연동, Upbit 미영향
# ---------------------------------------------------------------------------


def test_safety_guard_blocks_buy_outside_open_phase() -> None:
    from stock_platform.realtime.execution_models import (
        RealtimeExecutionMode,
    )
    from stock_platform.realtime.safety_guard import (
        RealtimeOrderSafetyGuard,
    )
    from stock_platform.realtime.safety_models import (
        RealtimeOrderSafetyConfig,
    )
    from stock_platform.realtime.strategy_models import (
        RealtimeSignal,
        RealtimeSignalAction,
    )

    d = date(2026, 8, 12)
    timeline = _regular_timeline(d)
    signal = RealtimeSignal(
        exchange_code="KRX",
        symbol="005930",
        action=RealtimeSignalAction.BUY,
        signal_price=Decimal("70000"),
        short_average=None,
        long_average=None,
        change_rate=Decimal("0.01"),
        reason_code="MA_GOLDEN_CROSS",
        generated_at=_at(d, time(15, 25)),
    )
    guard = RealtimeOrderSafetyGuard(RealtimeOrderSafetyConfig())

    with _patch_safety_guard_now(signal.generated_at), patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=timeline,
    ):
        decision = guard.evaluate(
            signal=signal,
            mode=RealtimeExecutionMode.PAPER,
            order_amount=Decimal("70000"),
            open_position_count=0,
        )
    assert decision.allowed is False
    assert decision.reason_code == (
        SessionTimelineReasonCode.MARKET_EXIT_ONLY.value
    )


def test_safety_guard_allows_sell_during_exit_only_phase() -> None:
    from stock_platform.realtime.execution_models import (
        RealtimeExecutionMode,
    )
    from stock_platform.realtime.safety_guard import (
        RealtimeOrderSafetyGuard,
    )
    from stock_platform.realtime.safety_models import (
        RealtimeOrderSafetyConfig,
    )
    from stock_platform.realtime.strategy_models import (
        RealtimeSignal,
        RealtimeSignalAction,
    )

    d = date(2026, 8, 13)
    timeline = _regular_timeline(d)
    signal = RealtimeSignal(
        exchange_code="KRX",
        symbol="005930",
        action=RealtimeSignalAction.SELL,
        signal_price=Decimal("70000"),
        short_average=None,
        long_average=None,
        change_rate=Decimal("-0.01"),
        reason_code="STOP_LOSS",
        generated_at=_at(d, time(15, 25)),
    )
    guard = RealtimeOrderSafetyGuard(RealtimeOrderSafetyConfig())

    with _patch_safety_guard_now(signal.generated_at), patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=timeline,
    ):
        decision = guard.evaluate(
            signal=signal,
            mode=RealtimeExecutionMode.PAPER,
            order_amount=Decimal("70000"),
            open_position_count=0,
        )
    assert decision.allowed is True


def test_safety_guard_upbit_unaffected_by_krx_timeline_patch() -> None:
    """Upbit 신호는 Session Timeline Patch와 무관하게 항상 시간 게이트 면제."""

    from stock_platform.realtime.execution_models import (
        RealtimeExecutionMode,
    )
    from stock_platform.realtime.safety_guard import (
        RealtimeOrderSafetyGuard,
    )
    from stock_platform.realtime.safety_models import (
        RealtimeOrderSafetyConfig,
    )
    from stock_platform.realtime.strategy_models import (
        RealtimeSignal,
        RealtimeSignalAction,
    )

    d = date(2026, 8, 14)
    # CLOSED Phase Timeline을 주더라도 Upbit 신호에는 영향이 없어야 한다.
    closed_timeline = _resolver().resolve_from_decision(
        exchange_code="KRX",
        market_date=d,
        is_trading_day=False,
        live_allowed=False,
        reason_code=CalendarReasonCode.CALENDAR_CLOSED.value,
        session_type=CalendarSessionType.CLOSED.value,
        regular_open_at=None,
        regular_close_at=None,
        revision=1,
    )
    signal = RealtimeSignal(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        action=RealtimeSignalAction.BUY,
        signal_price=Decimal("100000000"),
        short_average=None,
        long_average=None,
        change_rate=Decimal("0.01"),
        reason_code="MA_GOLDEN_CROSS",
        generated_at=_at(d, time(3, 0)),
    )
    guard = RealtimeOrderSafetyGuard(RealtimeOrderSafetyConfig())

    with patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=closed_timeline,
    ):
        decision = guard.evaluate(
            signal=signal,
            mode=RealtimeExecutionMode.PAPER,
            order_amount=Decimal("70000"),
            open_position_count=0,
        )
    assert decision.allowed is True


def test_upbit_timeline_stub_always_open() -> None:
    """UPBIT는 KRX Calendar Timeline과 완전히 분리된 24h Stub을 사용한다."""

    timeline = TradingSessionTimelineResolver().resolve_for_exchange(
        exchange_code="UPBIT",
        market_date=date(2026, 1, 1),  # 원단(설날) — KRX면 휴장
    )
    assert timeline.is_trading_day is True
    assert timeline.live_allowed is True
    assert timeline.phase_at(
        datetime(2026, 1, 1, 3, 0, tzinfo=ZoneInfo("UTC"))
    ) == TradingSessionPhase.OPEN


# ---------------------------------------------------------------------------
# Cron Fallback — 지연개장/조기종료 등 Timeline 불일치 Skip (Unit, Mock Timeline)
# ---------------------------------------------------------------------------


class _FakeCronSettings:
    krx_cron_fallback_enabled = True
    krx_cron_fallback_early_tolerance_minutes = 5
    krx_cron_fallback_late_tolerance_minutes = 60


def _fake_timeline(
    *, recovery_preopen_at=None, recovery_postclose_at=None, revision=9
):
    return SimpleNamespace(
        is_trading_day=True,
        live_allowed=True,
        recovery_preopen_at=recovery_preopen_at,
        recovery_postclose_at=recovery_postclose_at,
        revision=revision,
    )


def test_cron_fallback_skips_too_early() -> None:
    from stock_platform.broker.recovery_scheduler_service import (
        krx_cron_fallback_gate,
    )

    now = datetime.now(TZ)
    target = now + timedelta(minutes=40)  # early_tol=5분보다 훨씬 이전
    job = SimpleNamespace(last_run_at=None, last_status=None)

    with patch(
        "stock_platform.broker.recovery_scheduler_service.get_settings",
        return_value=_FakeCronSettings(),
    ), patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=_fake_timeline(recovery_preopen_at=target),
    ):
        result = krx_cron_fallback_gate(
            None, job_id="broker_recovery_kiwoom_preopen", job=job
        )

    assert result is not None
    assert result["status"] == "SKIPPED_TOO_EARLY"


def test_cron_fallback_skips_too_late() -> None:
    from stock_platform.broker.recovery_scheduler_service import (
        krx_cron_fallback_gate,
    )

    now = datetime.now(TZ)
    target = now - timedelta(minutes=90)  # late_tol=60분보다 훨씬 이후
    job = SimpleNamespace(last_run_at=None, last_status=None)

    with patch(
        "stock_platform.broker.recovery_scheduler_service.get_settings",
        return_value=_FakeCronSettings(),
    ), patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=_fake_timeline(recovery_postclose_at=target),
    ):
        result = krx_cron_fallback_gate(
            None, job_id="broker_recovery_kiwoom_postclose", job=job
        )

    assert result is not None
    assert result["status"] == "SKIPPED_TOO_LATE"


def test_cron_fallback_skips_already_executed() -> None:
    from stock_platform.broker.recovery_scheduler_service import (
        krx_cron_fallback_gate,
    )

    now = datetime.now(TZ)
    target = now - timedelta(minutes=2)  # 허용범위 내
    job = SimpleNamespace(
        last_run_at=target + timedelta(minutes=1),
        last_status="SUCCESS",
    )

    with patch(
        "stock_platform.broker.recovery_scheduler_service.get_settings",
        return_value=_FakeCronSettings(),
    ), patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=_fake_timeline(recovery_preopen_at=target),
    ):
        result = krx_cron_fallback_gate(
            None, job_id="broker_recovery_kiwoom_preopen", job=job
        )

    assert result is not None
    assert result["status"] == "SKIPPED_ALREADY_EXECUTED"


def test_cron_fallback_allows_within_tolerance_and_not_yet_run() -> None:
    from stock_platform.broker.recovery_scheduler_service import (
        krx_cron_fallback_gate,
    )

    now = datetime.now(TZ)
    target = now - timedelta(minutes=1)
    job = SimpleNamespace(last_run_at=None, last_status=None)

    with patch(
        "stock_platform.broker.recovery_scheduler_service.get_settings",
        return_value=_FakeCronSettings(),
    ), patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=_fake_timeline(recovery_preopen_at=target),
    ):
        result = krx_cron_fallback_gate(
            None, job_id="broker_recovery_kiwoom_preopen", job=job
        )

    assert result is None


def test_cron_fallback_disabled_by_setting() -> None:
    from stock_platform.broker.recovery_scheduler_service import (
        krx_cron_fallback_gate,
    )

    class _Disabled(_FakeCronSettings):
        krx_cron_fallback_enabled = False

    job = SimpleNamespace(last_run_at=None, last_status=None)
    with patch(
        "stock_platform.broker.recovery_scheduler_service.get_settings",
        return_value=_Disabled(),
    ):
        result = krx_cron_fallback_gate(
            None, job_id="broker_recovery_kiwoom_preopen", job=job
        )
    assert result is None


def test_cron_fallback_ignores_unknown_job_id() -> None:
    from stock_platform.broker.recovery_scheduler_service import (
        krx_cron_fallback_gate,
    )

    job = SimpleNamespace(last_run_at=None, last_status=None)
    with patch(
        "stock_platform.broker.recovery_scheduler_service.get_settings",
        return_value=_FakeCronSettings(),
    ):
        result = krx_cron_fallback_gate(
            None, job_id="broker_recovery_upbit_interval", job=job
        )
    assert result is None


# ---------------------------------------------------------------------------
# TradingCalendarService — Phase 기반 is_regular_session/require_live_order
# ---------------------------------------------------------------------------


class _FakeCalendarRepo:
    def __init__(self, rows: dict):
        self.rows = rows

    def get_day(self, *, exchange_code, calendar_date):
        return self.rows.get((exchange_code.upper(), calendar_date))


def _stored_day(d: date, **overrides):
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
        verified_status="VERIFIED",
        regular_open_at=time(9, 0),
        regular_close_at=time(15, 30),
        preopen_at=time(8, 30),
        timezone="Asia/Seoul",
        revision=1,
        verified_by="tester",
        verified_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_calendar_service_is_regular_session_exit_only_true() -> None:
    from stock_platform.operation.calendar_service import (
        TradingCalendarService,
    )

    d = date(2026, 8, 17)
    svc = TradingCalendarService(
        _FakeCalendarRepo({("KRX", d): _stored_day(d)})  # type: ignore[arg-type]
    )
    # 15:25 — EXIT_ONLY Phase → is_regular_session은 True (위험축소 허용대상)
    assert svc.is_regular_session("KRX", _at(d, time(15, 25))) is True
    # 16:00 — CLOSED
    assert svc.is_regular_session("KRX", _at(d, time(16, 0))) is False


def test_calendar_service_require_live_order_session_risk_reducing() -> None:
    from stock_platform.operation.calendar_service import (
        TradingCalendarService,
    )

    d = date(2026, 8, 18)
    svc = TradingCalendarService(
        _FakeCalendarRepo({("KRX", d): _stored_day(d)})  # type: ignore[arg-type]
    )
    moment = _at(d, time(15, 25))  # EXIT_ONLY

    # 위험축소가 아니면 차단
    try:
        svc.require_live_order_session(
            exchange_code="KRX", moment=moment, is_risk_reducing=False
        )
        raised = False
    except ValueError:
        raised = True
    assert raised is True

    # 위험축소면 허용
    decision = svc.require_live_order_session(
        exchange_code="KRX", moment=moment, is_risk_reducing=True
    )
    assert decision.live_allowed is True


def test_calendar_service_user_status_includes_phase_fields() -> None:
    from stock_platform.operation.calendar_service import (
        TradingCalendarService,
    )

    today = date.today()
    svc = TradingCalendarService(
        _FakeCalendarRepo({("KRX", today): _stored_day(today)})  # type: ignore[arg-type]
    )
    svc.next_trading_day = lambda **kwargs: today + timedelta(days=1)  # type: ignore[method-assign]
    status = svc.user_status("KRX")
    for key in (
        "phase",
        "new_entry_cutoff_at",
        "next_transition_at",
        "next_transition_phase",
        "is_delayed_open",
        "is_early_close",
        "new_entry_allowed",
        "risk_reducing_allowed",
    ):
        assert key in status
    assert "job_id" not in status
    assert "job_type" not in status


def test_calendar_cache_invalidate_also_clears_timeline_cache() -> None:
    from stock_platform.operation.session_timeline import (
        get_cached_timeline,
        put_cached_timeline,
    )

    d = date(2026, 8, 19)
    timeline = _regular_timeline(d, revision=42)
    put_cached_timeline(timeline)
    assert (
        get_cached_timeline(
            exchange_code="KRX", market_date=d, revision=42
        )
        is not None
    )
    invalidate_timeline_cache(exchange_code="KRX", market_date=d)
    assert (
        get_cached_timeline(
            exchange_code="KRX", market_date=d, revision=42
        )
        is None
    )


# ---------------------------------------------------------------------------
# krx_cron_fallback_timing — Snapshot/AI 게이트가 공유하는 순수 판정 함수
# ---------------------------------------------------------------------------


def test_krx_cron_fallback_timing_boundaries() -> None:
    target = _at(date(2026, 8, 20), time(15, 40))

    assert (
        krx_cron_fallback_timing(
            now=target - timedelta(minutes=10),
            target_at=target,
            early_tolerance_minutes=5,
            late_tolerance_minutes=60,
        )
        == "TOO_EARLY"
    )
    assert (
        krx_cron_fallback_timing(
            now=target,
            target_at=target,
            early_tolerance_minutes=5,
            late_tolerance_minutes=60,
        )
        == "WITHIN_WINDOW"
    )
    assert (
        krx_cron_fallback_timing(
            now=target + timedelta(minutes=59),
            target_at=target,
            early_tolerance_minutes=5,
            late_tolerance_minutes=60,
        )
        == "WITHIN_WINDOW"
    )
    assert (
        krx_cron_fallback_timing(
            now=target + timedelta(minutes=61),
            target_at=target,
            early_tolerance_minutes=5,
            late_tolerance_minutes=60,
        )
        == "TOO_LATE"
    )


# ---------------------------------------------------------------------------
# AutomaticScheduler — Snapshot/AI 고정 Cron의 Session Timeline Fallback 게이트
# ---------------------------------------------------------------------------


def _automatic_settings(**overrides):
    base = dict(
        scheduler_timezone="Asia/Seoul",
        scheduler_exchange_code="KRX",
        krx_cron_fallback_enabled=True,
        krx_cron_fallback_early_tolerance_minutes=5,
        krx_cron_fallback_late_tolerance_minutes=60,
        # STEP 8-5-15 — 기본은 레거시(직접 실행) 경로를 그대로 테스트하기
        # 위해 비활성화. 위임 동작은 별도 테스트에서 True로 검증한다.
        market_session_job_enabled=False,
        market_session_cron_wakeup_enabled=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_automatic_now(local_moment: datetime):
    class _FixedAutomaticDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D102
            if tz is None:
                return local_moment
            return local_moment.astimezone(tz)

    return patch(
        "stock_platform.scheduler.automatic.datetime",
        _FixedAutomaticDateTime,
    )


def _fake_session_factory():
    fake_session = MagicMock()
    fake_session.close = MagicMock()
    return lambda: fake_session


def test_automatic_gate_skips_non_trading_day() -> None:
    from stock_platform.scheduler.automatic import AutomaticScheduler

    scheduler = AutomaticScheduler(_automatic_settings())
    d = date(2026, 1, 1)
    closed = _resolver().resolve_from_decision(
        exchange_code="KRX",
        market_date=d,
        is_trading_day=False,
        live_allowed=False,
        reason_code=CalendarReasonCode.CALENDAR_CLOSED.value,
        session_type=CalendarSessionType.CLOSED.value,
        regular_open_at=None,
        regular_close_at=None,
        revision=1,
    )

    async def _run():
        with patch(
            "stock_platform.operation.session_timeline.resolve_krx_timeline",
            return_value=closed,
        ):
            return await scheduler._krx_session_cron_gate(
                job_name="portfolio_equity_snapshot",
                timeline_field="snapshot_at",
            )

    import asyncio

    result = asyncio.run(_run())
    assert result is not None
    assert result["status"] == "SKIPPED_NON_TRADING_DAY"


def test_automatic_gate_skips_calendar_unavailable() -> None:
    from stock_platform.scheduler.automatic import AutomaticScheduler

    scheduler = AutomaticScheduler(_automatic_settings())
    d = date(2026, 3, 2)
    unavailable = _resolver().resolve_from_decision(
        exchange_code="KRX",
        market_date=d,
        is_trading_day=False,
        live_allowed=False,
        reason_code=CalendarReasonCode.CALENDAR_MISSING.value,
        session_type=None,
        regular_open_at=None,
        regular_close_at=None,
        revision=0,
    )

    async def _run():
        with patch(
            "stock_platform.operation.session_timeline.resolve_krx_timeline",
            return_value=unavailable,
        ):
            return await scheduler._krx_session_cron_gate(
                job_name="ai_orchestration",
                timeline_field="analysis_at",
            )

    import asyncio

    result = asyncio.run(_run())
    assert result is not None
    assert result["status"] == "SKIPPED_CALENDAR_UNAVAILABLE"


@pytest.mark.asyncio
async def test_automatic_gate_skips_too_early() -> None:
    from stock_platform.scheduler.automatic import AutomaticScheduler

    scheduler = AutomaticScheduler(_automatic_settings())
    d = date(2026, 8, 21)
    timeline = _regular_timeline(d)  # snapshot_at == 15:40

    with _patch_automatic_now(_at(d, time(15, 0))), patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=timeline,
    ):
        result = await scheduler._krx_session_cron_gate(
            job_name="portfolio_equity_snapshot",
            timeline_field="snapshot_at",
        )

    assert result is not None
    assert result["status"] == "SKIPPED_TOO_EARLY"


@pytest.mark.asyncio
async def test_automatic_gate_skips_too_late() -> None:
    from stock_platform.scheduler.automatic import AutomaticScheduler

    scheduler = AutomaticScheduler(_automatic_settings())
    d = date(2026, 8, 24)
    timeline = _regular_timeline(d)  # analysis_at == 16:00

    with _patch_automatic_now(_at(d, time(17, 30))), patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=timeline,
    ):
        result = await scheduler._krx_session_cron_gate(
            job_name="ai_orchestration",
            timeline_field="analysis_at",
        )

    assert result is not None
    assert result["status"] == "SKIPPED_TOO_LATE"


@pytest.mark.asyncio
async def test_automatic_gate_skips_already_executed() -> None:
    from stock_platform.scheduler.automatic import AutomaticScheduler

    scheduler = AutomaticScheduler(_automatic_settings())
    d = date(2026, 8, 25)
    timeline = _regular_timeline(d)  # snapshot_at == 15:40
    last_run = _at(d, time(15, 41)).astimezone(timezone.utc)
    fake_row = SimpleNamespace(started_at=last_run)

    with _patch_automatic_now(_at(d, time(15, 45))), patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=timeline,
    ), patch(
        "stock_platform.scheduler.automatic.get_session_factory",
        return_value=_fake_session_factory(),
    ), patch(
        "stock_platform.operation.job_repository.JobRunRepository.list_recent",
        return_value=[fake_row],
    ):
        result = await scheduler._krx_session_cron_gate(
            job_name="portfolio_equity_snapshot",
            timeline_field="snapshot_at",
        )

    assert result is not None
    assert result["status"] == "SKIPPED_ALREADY_EXECUTED"


@pytest.mark.asyncio
async def test_automatic_gate_allows_when_not_yet_run() -> None:
    from stock_platform.scheduler.automatic import AutomaticScheduler

    scheduler = AutomaticScheduler(_automatic_settings())
    d = date(2026, 8, 26)
    timeline = _regular_timeline(d)  # snapshot_at == 15:40

    with _patch_automatic_now(_at(d, time(15, 41))), patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=timeline,
    ), patch(
        "stock_platform.scheduler.automatic.get_session_factory",
        return_value=_fake_session_factory(),
    ), patch(
        "stock_platform.operation.job_repository.JobRunRepository.list_recent",
        return_value=[],
    ):
        result = await scheduler._krx_session_cron_gate(
            job_name="portfolio_equity_snapshot",
            timeline_field="snapshot_at",
        )

    assert result is None


@pytest.mark.asyncio
async def test_automatic_gate_delegates_to_market_session_job_when_enabled() -> None:
    """STEP 8-5-15 — market_session_job_enabled면 직접 실행 대신 위임한다."""

    from stock_platform.scheduler.automatic import AutomaticScheduler

    scheduler = AutomaticScheduler(
        _automatic_settings(
            market_session_job_enabled=True,
            market_session_cron_wakeup_enabled=True,
        )
    )
    d = date(2026, 8, 26)
    timeline = _regular_timeline(d)  # snapshot_at == 15:40

    fake_wakeup_service = MagicMock()
    fake_wakeup_service.ensure_wakeup.return_value = {
        "status": "WOKEN",
        "job_id": 123,
    }

    with _patch_automatic_now(_at(d, time(15, 41))), patch(
        "stock_platform.operation.session_timeline.resolve_krx_timeline",
        return_value=timeline,
    ), patch(
        "stock_platform.scheduler.automatic.get_session_factory",
        return_value=_fake_session_factory(),
    ), patch(
        "stock_platform.operation.job_repository.JobRunRepository.list_recent",
        return_value=[],
    ), patch(
        "stock_platform.operation.market_session_job_service.MarketSessionJobService",
        return_value=fake_wakeup_service,
    ):
        result = await scheduler._krx_session_cron_gate(
            job_name="portfolio_equity_snapshot",
            timeline_field="snapshot_at",
        )

    assert result is not None
    assert result["status"] == "DELEGATED_TO_MARKET_SESSION_JOB"
    fake_wakeup_service.ensure_wakeup.assert_called_once_with(
        exchange_code="KRX",
        job_type="KRX_EQUITY_SNAPSHOT",
        market_date=d,
    )


@pytest.mark.asyncio
async def test_automatic_gate_disabled_by_setting() -> None:
    from stock_platform.scheduler.automatic import AutomaticScheduler

    scheduler = AutomaticScheduler(
        _automatic_settings(krx_cron_fallback_enabled=False)
    )
    result = await scheduler._krx_session_cron_gate(
        job_name="portfolio_equity_snapshot",
        timeline_field="snapshot_at",
    )
    assert result is None


@pytest.mark.asyncio
async def test_automatic_gate_ignored_for_non_krx_exchange() -> None:
    from stock_platform.scheduler.automatic import AutomaticScheduler

    scheduler = AutomaticScheduler(
        _automatic_settings(scheduler_exchange_code="UPBIT")
    )
    result = await scheduler._krx_session_cron_gate(
        job_name="portfolio_equity_snapshot",
        timeline_field="snapshot_at",
    )
    assert result is None


@pytest.mark.asyncio
async def test_execute_registered_job_calls_gate_when_not_forced() -> None:
    """SESSION_DEPENDENT Job은 force=False(스케줄 Cron 실행)면 게이트를 거친다."""

    from stock_platform.scheduler.automatic import AutomaticScheduler

    scheduler = AutomaticScheduler(_automatic_settings())
    scheduler._krx_session_cron_gate = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "status": "SKIPPED_TOO_EARLY",
            "job_name": "portfolio_equity_snapshot",
        }
    )

    result = await scheduler._execute_registered_job(
        job_name="portfolio_equity_snapshot",
        payload={},
        gate_timeline_field="snapshot_at",
        force=False,
    )

    scheduler._krx_session_cron_gate.assert_called_once()
    assert result["status"] == "SKIPPED_TOO_EARLY"


@pytest.mark.asyncio
async def test_execute_registered_job_skips_gate_when_forced() -> None:
    """ADMIN 수동 즉시실행(force=True)은 Cron Fallback 게이트를 건너뛴다."""

    from stock_platform.scheduler.automatic import AutomaticScheduler

    scheduler = AutomaticScheduler(_automatic_settings())
    scheduler._krx_session_cron_gate = AsyncMock(return_value=None)  # type: ignore[method-assign]

    fake_history = SimpleNamespace(job_run_id=1, status_code="SUCCESS")
    fake_scheduler_service = MagicMock()
    fake_scheduler_service.execute = AsyncMock(
        return_value=(fake_history, {"ok": True})
    )

    with patch(
        "stock_platform.scheduler.automatic.get_session_factory",
        return_value=_fake_session_factory(),
    ), patch(
        "stock_platform.scheduler.automatic.SchedulerService",
        return_value=fake_scheduler_service,
    ):
        result = await scheduler._execute_registered_job(
            job_name="portfolio_equity_snapshot",
            payload={},
            gate_timeline_field="snapshot_at",
            force=True,
        )

    scheduler._krx_session_cron_gate.assert_not_called()
    assert result["status_code"] == "SUCCESS"
