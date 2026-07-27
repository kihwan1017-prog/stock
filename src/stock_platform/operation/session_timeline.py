"""STEP 8-5-13 — KRX Trading Session Timeline / Phase."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from stock_platform.operation.calendar_constants import (
    CALENDAR_UNAVAILABLE_REASONS,
    KRX_TIMEZONE,
    CalendarSessionType,
)


class TradingSessionPhase(StrEnum):
    """Calendar 기준 운영 Phase (Realtime PRE_MARKET 등과 별개)."""

    NON_TRADING_DAY = "NON_TRADING_DAY"
    PREOPEN = "PREOPEN"
    OPEN = "OPEN"
    EXIT_ONLY = "EXIT_ONLY"
    CLOSED = "CLOSED"
    POST_CLOSE = "POST_CLOSE"
    CALENDAR_UNAVAILABLE = "CALENDAR_UNAVAILABLE"


class SessionTimelineReasonCode(StrEnum):
    MARKET_PREOPEN = "MARKET_PREOPEN"
    MARKET_EXIT_ONLY = "MARKET_EXIT_ONLY"
    MARKET_CLOSED = "MARKET_CLOSED"
    MARKET_NON_TRADING_DAY = "MARKET_NON_TRADING_DAY"
    CALENDAR_UNAVAILABLE = "CALENDAR_UNAVAILABLE"
    CALENDAR_STALE = "CALENDAR_STALE"
    CALENDAR_REVISION_CHANGED = "CALENDAR_REVISION_CHANGED"
    SPECIAL_SESSION_RESTRICTION = "SPECIAL_SESSION_RESTRICTION"
    MARKET_OPEN = "MARKET_OPEN"


@dataclass(frozen=True, slots=True)
class TradingSessionTimeline:
    exchange_code: str
    market_date: date
    revision: int
    timezone: str
    session_type: str | None
    is_trading_day: bool
    live_allowed: bool
    reason_code: str
    preopen_start_at: datetime | None
    order_entry_start_at: datetime | None
    regular_open_at: datetime | None
    new_entry_cutoff_at: datetime | None
    regular_close_at: datetime | None
    post_close_start_at: datetime | None
    recovery_preopen_at: datetime | None
    recovery_postclose_at: datetime | None
    snapshot_at: datetime | None
    settlement_at: datetime | None
    analysis_at: datetime | None

    def phase_at(self, moment: datetime) -> TradingSessionPhase:
        # Fail Closed — Calendar 자체를 신뢰할 수 없는 상태
        # (MISSING/UNVERIFIED/STALE/CONFLICT/UNAVAILABLE)는 단순
        # "휴장(NON_TRADING_DAY)"과 구분해 CALENDAR_UNAVAILABLE로 취급한다.
        if self.reason_code in CALENDAR_UNAVAILABLE_REASONS:
            return TradingSessionPhase.CALENDAR_UNAVAILABLE

        if not self.is_trading_day or not self.live_allowed:
            return TradingSessionPhase.NON_TRADING_DAY

        local = _aware(moment, self.timezone)
        open_at = self.regular_open_at
        close_at = self.regular_close_at
        preopen = self.preopen_start_at
        cutoff = self.new_entry_cutoff_at
        post = self.post_close_start_at

        if open_at is None or close_at is None:
            return TradingSessionPhase.CALENDAR_UNAVAILABLE

        if preopen and preopen <= local < open_at:
            return TradingSessionPhase.PREOPEN
        if local < open_at:
            return TradingSessionPhase.PREOPEN
        if cutoff and open_at <= local < cutoff:
            return TradingSessionPhase.OPEN
        if cutoff and cutoff <= local < close_at:
            return TradingSessionPhase.EXIT_ONLY
        if open_at <= local < close_at and cutoff is None:
            return TradingSessionPhase.OPEN
        if close_at <= local and (post is None or local < post):
            return TradingSessionPhase.CLOSED
        if post and local >= post:
            return TradingSessionPhase.POST_CLOSE
        return TradingSessionPhase.CLOSED

    def allows_new_entry(self, moment: datetime) -> bool:
        return self.phase_at(moment) == TradingSessionPhase.OPEN

    def allows_risk_reducing(self, moment: datetime) -> bool:
        phase = self.phase_at(moment)
        return phase in {
            TradingSessionPhase.OPEN,
            TradingSessionPhase.EXIT_ONLY,
        }

    def allows_any_order(self, moment: datetime, *, is_risk_reducing: bool) -> bool:
        phase = self.phase_at(moment)
        if phase == TradingSessionPhase.OPEN:
            return True
        if phase == TradingSessionPhase.EXIT_ONLY and is_risk_reducing:
            return True
        return False

    def next_transition(
        self, moment: datetime
    ) -> tuple[datetime | None, "TradingSessionPhase | None"]:
        """현재 시각 이후 다음 Phase 전환 시각과 전환될 Phase."""

        local = _aware(moment, self.timezone)
        candidates: list[tuple[datetime, TradingSessionPhase]] = []
        if self.preopen_start_at:
            candidates.append(
                (self.preopen_start_at, TradingSessionPhase.PREOPEN)
            )
        if self.regular_open_at:
            candidates.append(
                (self.regular_open_at, TradingSessionPhase.OPEN)
            )
        if self.new_entry_cutoff_at:
            candidates.append(
                (self.new_entry_cutoff_at, TradingSessionPhase.EXIT_ONLY)
            )
        if self.regular_close_at:
            candidates.append(
                (self.regular_close_at, TradingSessionPhase.CLOSED)
            )
        if self.post_close_start_at:
            candidates.append(
                (self.post_close_start_at, TradingSessionPhase.POST_CLOSE)
            )
        upcoming = sorted(
            (c for c in candidates if c[0] > local), key=lambda c: c[0]
        )
        if not upcoming:
            return None, None
        return upcoming[0]

    def to_dict(self) -> dict[str, Any]:
        def _iso(v: datetime | None) -> str | None:
            return v.isoformat() if v else None

        return {
            "exchange_code": self.exchange_code,
            "market_date": self.market_date.isoformat(),
            "revision": self.revision,
            "timezone": self.timezone,
            "session_type": self.session_type,
            "is_trading_day": self.is_trading_day,
            "live_allowed": self.live_allowed,
            "reason_code": self.reason_code,
            "preopen_start_at": _iso(self.preopen_start_at),
            "order_entry_start_at": _iso(self.order_entry_start_at),
            "regular_open_at": _iso(self.regular_open_at),
            "new_entry_cutoff_at": _iso(self.new_entry_cutoff_at),
            "regular_close_at": _iso(self.regular_close_at),
            "post_close_start_at": _iso(self.post_close_start_at),
            "recovery_preopen_at": _iso(self.recovery_preopen_at),
            "recovery_postclose_at": _iso(self.recovery_postclose_at),
            "snapshot_at": _iso(self.snapshot_at),
            "settlement_at": _iso(self.settlement_at),
            "analysis_at": _iso(self.analysis_at),
        }


def _aware(moment: datetime, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=tz)
    return moment.astimezone(tz)


def _combine(d: date, t: time, tz_name: str) -> datetime:
    return datetime.combine(d, t, tzinfo=ZoneInfo(tz_name))


@dataclass(frozen=True, slots=True)
class SessionOffsetConfig:
    preopen_minutes_before_open: int = 30
    recovery_preopen_minutes_before_open: int = 30
    new_entry_cutoff_minutes_before_close: int = 10
    recovery_postclose_minutes_after_close: int = 10
    snapshot_minutes_after_close: int = 10
    settlement_minutes_after_close: int = 20
    ai_analysis_minutes_after_close: int = 30


def load_session_offset_config() -> SessionOffsetConfig:
    try:
        from stock_platform.common.settings import get_settings

        s = get_settings()
        return SessionOffsetConfig(
            preopen_minutes_before_open=int(
                s.krx_preopen_minutes_before_open
            ),
            recovery_preopen_minutes_before_open=int(
                s.krx_recovery_preopen_minutes_before_open
            ),
            new_entry_cutoff_minutes_before_close=int(
                s.krx_new_entry_cutoff_minutes_before_close
            ),
            recovery_postclose_minutes_after_close=int(
                s.krx_recovery_postclose_minutes_after_close
            ),
            snapshot_minutes_after_close=int(
                s.krx_snapshot_minutes_after_close
            ),
            settlement_minutes_after_close=int(
                s.krx_settlement_minutes_after_close
            ),
            ai_analysis_minutes_after_close=int(
                s.krx_ai_analysis_minutes_after_close
            ),
        )
    except Exception:  # noqa: BLE001
        return SessionOffsetConfig()


class TradingSessionTimelineResolver:
    """Calendar Day → timezone-aware Session Timeline."""

    def __init__(
        self,
        offsets: SessionOffsetConfig | None = None,
    ) -> None:
        self._offsets = offsets or load_session_offset_config()

    def resolve_from_decision(
        self,
        *,
        exchange_code: str,
        market_date: date,
        is_trading_day: bool,
        live_allowed: bool,
        reason_code: str,
        session_type: str | None,
        regular_open_at: time | None,
        regular_close_at: time | None,
        preopen_at: time | None = None,
        revision: int = 0,
        timezone: str = KRX_TIMEZONE,
    ) -> TradingSessionTimeline:
        exchange = exchange_code.strip().upper()
        tz = timezone or KRX_TIMEZONE

        if not is_trading_day or not live_allowed:
            return TradingSessionTimeline(
                exchange_code=exchange,
                market_date=market_date,
                revision=int(revision or 0),
                timezone=tz,
                session_type=session_type
                or CalendarSessionType.CLOSED.value,
                is_trading_day=bool(is_trading_day),
                live_allowed=bool(live_allowed),
                reason_code=reason_code,
                preopen_start_at=None,
                order_entry_start_at=None,
                regular_open_at=None,
                new_entry_cutoff_at=None,
                regular_close_at=None,
                post_close_start_at=None,
                recovery_preopen_at=None,
                recovery_postclose_at=None,
                snapshot_at=None,
                settlement_at=None,
                analysis_at=None,
            )

        open_t = regular_open_at or time(9, 0)
        close_t = regular_close_at or time(15, 30)
        open_dt = _combine(market_date, open_t, tz)
        close_dt = _combine(market_date, close_t, tz)

        # Cutoff가 장 길이보다 크면 open으로 클램프
        cutoff_mins = min(
            self._offsets.new_entry_cutoff_minutes_before_close,
            max(
                0,
                int((close_dt - open_dt).total_seconds() // 60) - 1,
            ),
        )
        cutoff_dt = close_dt - timedelta(minutes=cutoff_mins)

        if preopen_at is not None:
            preopen_dt = _combine(market_date, preopen_at, tz)
        else:
            preopen_dt = open_dt - timedelta(
                minutes=self._offsets.preopen_minutes_before_open
            )

        recovery_pre = open_dt - timedelta(
            minutes=self._offsets.recovery_preopen_minutes_before_open
        )
        recovery_post = close_dt + timedelta(
            minutes=self._offsets.recovery_postclose_minutes_after_close
        )
        snapshot = close_dt + timedelta(
            minutes=self._offsets.snapshot_minutes_after_close
        )
        settlement = close_dt + timedelta(
            minutes=self._offsets.settlement_minutes_after_close
        )
        analysis = close_dt + timedelta(
            minutes=self._offsets.ai_analysis_minutes_after_close
        )

        return TradingSessionTimeline(
            exchange_code=exchange,
            market_date=market_date,
            revision=int(revision or 0),
            timezone=tz,
            session_type=session_type
            or CalendarSessionType.REGULAR.value,
            is_trading_day=True,
            live_allowed=True,
            reason_code=reason_code,
            preopen_start_at=preopen_dt,
            order_entry_start_at=open_dt,
            regular_open_at=open_dt,
            new_entry_cutoff_at=cutoff_dt,
            regular_close_at=close_dt,
            post_close_start_at=recovery_post,
            recovery_preopen_at=recovery_pre,
            recovery_postclose_at=recovery_post,
            snapshot_at=snapshot,
            settlement_at=settlement,
            analysis_at=analysis,
        )

    def resolve_for_exchange(
        self,
        *,
        exchange_code: str,
        market_date: date | None = None,
        moment: datetime | None = None,
    ) -> TradingSessionTimeline:
        """TradingCalendarService.evaluate 기반 Timeline."""

        from stock_platform.operation.calendar_repository import (
            TradingCalendarRepository,
        )
        from stock_platform.operation.calendar_service import (
            TradingCalendarService,
        )
        from stock_platform.database.session import get_session_factory

        exchange = exchange_code.strip().upper()
        tz = ZoneInfo(KRX_TIMEZONE)
        if moment is not None:
            local = _aware(moment, KRX_TIMEZONE)
            d = market_date or local.date()
        else:
            d = market_date or datetime.now(tz).date()

        if exchange == "UPBIT":
            # Crypto — KRX Timeline 비적용 (항상 open-like stub)
            now_open = _combine(d, time(0, 0), KRX_TIMEZONE)
            now_close = _combine(d, time(23, 59, 59), KRX_TIMEZONE)
            return TradingSessionTimeline(
                exchange_code=exchange,
                market_date=d,
                revision=0,
                timezone="UTC",
                session_type=CalendarSessionType.REGULAR.value,
                is_trading_day=True,
                live_allowed=True,
                reason_code="ALWAYS_OPEN",
                preopen_start_at=now_open,
                order_entry_start_at=now_open,
                regular_open_at=now_open,
                new_entry_cutoff_at=now_close,
                regular_close_at=now_close,
                post_close_start_at=None,
                recovery_preopen_at=None,
                recovery_postclose_at=None,
                snapshot_at=None,
                settlement_at=None,
                analysis_at=None,
            )

        session = get_session_factory()()
        try:
            repo = TradingCalendarRepository(session)
            svc = TradingCalendarService(repo)
            decision = svc.evaluate(
                exchange_code=exchange, calendar_date=d
            )
            stored = repo.get_day(
                exchange_code=exchange, calendar_date=d
            )
            revision = int(getattr(stored, "revision", 0) or 0)
            preopen = getattr(stored, "preopen_at", None) if stored else None
            return self.resolve_from_decision(
                exchange_code=exchange,
                market_date=d,
                is_trading_day=decision.is_trading_day,
                live_allowed=decision.live_allowed,
                reason_code=decision.reason_code,
                session_type=decision.session_type,
                regular_open_at=decision.regular_open_at,
                regular_close_at=decision.regular_close_at,
                preopen_at=preopen,
                revision=revision,
                timezone=decision.timezone or KRX_TIMEZONE,
            )
        finally:
            session.close()


# Timeline Cache — revision 포함, calendar_cache와 병행
_TIMELINE_CACHE: dict[tuple[str, date, int], tuple[float, TradingSessionTimeline]] = {}
_TIMELINE_CACHE_TTL = 2.0


def get_cached_timeline(
    *,
    exchange_code: str,
    market_date: date,
    revision: int,
) -> TradingSessionTimeline | None:
    import time as time_mod

    key = (exchange_code.upper(), market_date, int(revision))
    item = _TIMELINE_CACHE.get(key)
    if item is None:
        return None
    expires, timeline = item
    if time_mod.monotonic() > expires:
        _TIMELINE_CACHE.pop(key, None)
        return None
    return timeline


def put_cached_timeline(timeline: TradingSessionTimeline) -> None:
    import time as time_mod

    try:
        from stock_platform.common.settings import get_settings

        ttl = float(get_settings().krx_calendar_cache_ttl_seconds)
    except Exception:  # noqa: BLE001
        ttl = _TIMELINE_CACHE_TTL
    key = (
        timeline.exchange_code.upper(),
        timeline.market_date,
        int(timeline.revision),
    )
    _TIMELINE_CACHE[key] = (time_mod.monotonic() + ttl, timeline)


def invalidate_timeline_cache(
    *,
    exchange_code: str | None = None,
    market_date: date | None = None,
) -> None:
    if exchange_code is None and market_date is None:
        _TIMELINE_CACHE.clear()
        return
    dead = [
        k
        for k in _TIMELINE_CACHE
        if (exchange_code is None or k[0] == exchange_code.upper())
        and (market_date is None or k[1] == market_date)
    ]
    for k in dead:
        _TIMELINE_CACHE.pop(k, None)


# Phase 변경 Audit — Tick마다 남기지 않고 실제 전환 시에만 기록
_LAST_OBSERVED_PHASE: dict[str, str] = {}


def _audit_phase_change_if_needed(
    timeline: TradingSessionTimeline, moment: datetime
) -> None:
    try:
        phase = timeline.phase_at(moment).value
    except Exception:  # noqa: BLE001
        return
    key = timeline.exchange_code.upper()
    previous = _LAST_OBSERVED_PHASE.get(key)
    if previous == phase:
        return
    _LAST_OBSERVED_PHASE[key] = phase
    if previous is None:
        # 프로세스 기동 직후 최초 관측은 Audit 대상 아님
        return
    try:
        from stock_platform.operation.calendar_audit import (
            audit_calendar_event,
        )

        audit_calendar_event(
            "KRX_SESSION_PHASE_CHANGED",
            detail={
                "exchange_code": key,
                "from_phase": previous,
                "to_phase": phase,
                "revision": timeline.revision,
                "market_date": timeline.market_date.isoformat(),
            },
        )
    except Exception:  # noqa: BLE001
        pass


def resolve_krx_timeline(
    *,
    market_date: date | None = None,
    moment: datetime | None = None,
) -> TradingSessionTimeline:
    """공통 진입점 — Cache + Resolver."""

    resolver = TradingSessionTimelineResolver()
    timeline = resolver.resolve_for_exchange(
        exchange_code="KRX",
        market_date=market_date,
        moment=moment,
    )
    now = moment or datetime.now(ZoneInfo(KRX_TIMEZONE))
    cached = get_cached_timeline(
        exchange_code="KRX",
        market_date=timeline.market_date,
        revision=timeline.revision,
    )
    if cached is not None:
        _audit_phase_change_if_needed(cached, now)
        return cached
    put_cached_timeline(timeline)
    _audit_phase_change_if_needed(timeline, now)
    return timeline


def krx_cron_fallback_timing(
    *,
    now: datetime,
    target_at: datetime,
    early_tolerance_minutes: int,
    late_tolerance_minutes: int,
) -> str:
    """08:30/15:40/16:00·16:30 등 고정 Cron이 실제 Timeline 목표 시각과

    얼마나 벗어났는지 분류하는 순수 함수. `broker/recovery_scheduler_service`
    의 ``krx_cron_fallback_gate``와 ``scheduler/automatic``의 Snapshot/AI
    게이트가 이 판정을 공유한다 (지연개장/조기종료 등으로 고정 Cron 시각과
    Timeline이 어긋나는 경우를 동일한 규칙으로 취급하기 위함).

    반환값: ``"TOO_EARLY"`` | ``"TOO_LATE"`` | ``"WITHIN_WINDOW"``
    """

    if now < target_at - timedelta(minutes=early_tolerance_minutes):
        return "TOO_EARLY"
    if now > target_at + timedelta(minutes=late_tolerance_minutes):
        return "TOO_LATE"
    return "WITHIN_WINDOW"


def phase_reason_code(phase: TradingSessionPhase) -> str:
    mapping = {
        TradingSessionPhase.PREOPEN: SessionTimelineReasonCode.MARKET_PREOPEN.value,
        TradingSessionPhase.EXIT_ONLY: SessionTimelineReasonCode.MARKET_EXIT_ONLY.value,
        TradingSessionPhase.CLOSED: SessionTimelineReasonCode.MARKET_CLOSED.value,
        TradingSessionPhase.POST_CLOSE: SessionTimelineReasonCode.MARKET_CLOSED.value,
        TradingSessionPhase.NON_TRADING_DAY: SessionTimelineReasonCode.MARKET_NON_TRADING_DAY.value,
        TradingSessionPhase.CALENDAR_UNAVAILABLE: SessionTimelineReasonCode.CALENDAR_UNAVAILABLE.value,
        TradingSessionPhase.OPEN: SessionTimelineReasonCode.MARKET_OPEN.value,
    }
    return mapping[phase]
