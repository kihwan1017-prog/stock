"""STEP 8-5-7 — DB 기반 Trading Calendar (WEEKDAY_FALLBACK Fail Closed)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from stock_platform.operation.calendar_constants import (
    CALENDAR_UNAVAILABLE_REASONS,
    CalendarReasonCode,
    CalendarSessionType,
    CalendarVerifiedStatus,
    KRX_TIMEZONE,
)
from stock_platform.operation.calendar_repository import (
    TradingCalendarRepository,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TradingDayDecision:
    exchange_code: str
    calendar_date: date
    is_trading_day: bool
    reason_code: str
    holiday_name: str | None
    source_code: str
    session_type: str | None = None
    verified_status: str | None = None
    regular_open_at: time | None = None
    regular_close_at: time | None = None
    timezone: str = KRX_TIMEZONE
    live_allowed: bool = False


@dataclass(frozen=True, slots=True)
class CoverageReport:
    exchange_code: str
    from_date: date
    to_date: date
    expected_calendar_days: int
    stored_days: int
    missing_days: int
    verified_trading_days: int
    coverage_complete: bool
    by_verified_status: dict[str, int]
    live_trading_allowed: bool
    message: str


class TradingCalendarService:
    """거래일·세션·Coverage. UPBIT는 24h ALWAYS_OPEN."""

    ALWAYS_OPEN_EXCHANGES = {"UPBIT"}

    def __init__(
        self,
        repository: TradingCalendarRepository,
        *,
        allow_weekday_fallback: bool | None = None,
    ) -> None:
        self._repository = repository
        if allow_weekday_fallback is None:
            try:
                from stock_platform.common.settings import get_settings

                allow_weekday_fallback = bool(
                    get_settings().krx_calendar_allow_weekday_fallback
                )
            except Exception:  # noqa: BLE001
                allow_weekday_fallback = False
        self._allow_weekday_fallback = bool(allow_weekday_fallback)

    def get_calendar(
        self,
        exchange_code: str,
        calendar_date: date,
    ):
        return self._repository.get_day(
            exchange_code=exchange_code,
            calendar_date=calendar_date,
        )

    def evaluate(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
    ) -> TradingDayDecision:
        exchange = exchange_code.strip().upper()

        if exchange in self.ALWAYS_OPEN_EXCHANGES:
            return TradingDayDecision(
                exchange_code=exchange,
                calendar_date=calendar_date,
                is_trading_day=True,
                reason_code=CalendarReasonCode.ALWAYS_OPEN.value,
                holiday_name=None,
                source_code="SYSTEM",
                session_type=CalendarSessionType.REGULAR.value,
                verified_status=CalendarVerifiedStatus.VERIFIED.value,
                live_allowed=True,
                timezone="UTC",
            )

        stored = self._repository.get_day(
            exchange_code=exchange,
            calendar_date=calendar_date,
        )

        if stored is None:
            if calendar_date.weekday() >= 5:
                return TradingDayDecision(
                    exchange_code=exchange,
                    calendar_date=calendar_date,
                    is_trading_day=False,
                    reason_code=CalendarReasonCode.WEEKEND.value,
                    holiday_name=None,
                    source_code="SYSTEM",
                    session_type=CalendarSessionType.CLOSED.value,
                    verified_status=CalendarVerifiedStatus.MISSING.value,
                    live_allowed=False,
                )
            if self._allow_weekday_fallback:
                logger.warning(
                    "WEEKDAY_FALLBACK used exchange=%s date=%s "
                    "(dev/test only)",
                    exchange,
                    calendar_date,
                )
                try:
                    from stock_platform.operation.calendar_audit import (
                        audit_calendar_event,
                    )

                    audit_calendar_event(
                        "CALENDAR_WEEKDAY_FALLBACK_USED",
                        detail={
                            "exchange_code": exchange,
                            "calendar_date": calendar_date.isoformat(),
                        },
                    )
                except Exception:  # noqa: BLE001
                    pass
                return TradingDayDecision(
                    exchange_code=exchange,
                    calendar_date=calendar_date,
                    is_trading_day=True,
                    reason_code=CalendarReasonCode.WEEKDAY_FALLBACK.value,
                    holiday_name=None,
                    source_code="SYSTEM",
                    session_type=CalendarSessionType.REGULAR.value,
                    verified_status=CalendarVerifiedStatus.UNVERIFIED.value,
                    live_allowed=False,
                    regular_open_at=time(9, 0),
                    regular_close_at=time(15, 30),
                )
            return TradingDayDecision(
                exchange_code=exchange,
                calendar_date=calendar_date,
                is_trading_day=False,
                reason_code=CalendarReasonCode.CALENDAR_MISSING.value,
                holiday_name=None,
                source_code="SYSTEM",
                session_type=None,
                verified_status=CalendarVerifiedStatus.MISSING.value,
                live_allowed=False,
            )

        status = (stored.verified_status or "").upper()
        if status == CalendarVerifiedStatus.STALE.value:
            return self._from_stored(
                stored,
                reason=CalendarReasonCode.CALENDAR_STALE.value,
                is_trading_day=False,
                live_allowed=False,
            )
        if status == CalendarVerifiedStatus.CONFLICT.value:
            return self._from_stored(
                stored,
                reason=CalendarReasonCode.CALENDAR_CONFLICT.value,
                is_trading_day=False,
                live_allowed=False,
            )
        if status != CalendarVerifiedStatus.VERIFIED.value:
            return self._from_stored(
                stored,
                reason=CalendarReasonCode.CALENDAR_UNVERIFIED.value,
                is_trading_day=False,
                live_allowed=False,
            )

        if stored.is_trading_day:
            return self._from_stored(
                stored,
                reason=CalendarReasonCode.CALENDAR_OPEN.value,
                is_trading_day=True,
                live_allowed=True,
            )
        return self._from_stored(
            stored,
            reason=CalendarReasonCode.CALENDAR_CLOSED.value,
            is_trading_day=False,
            live_allowed=False,
        )

    def _from_stored(
        self,
        stored,
        *,
        reason: str,
        is_trading_day: bool,
        live_allowed: bool,
    ) -> TradingDayDecision:
        return TradingDayDecision(
            exchange_code=stored.exchange_code,
            calendar_date=stored.calendar_date,
            is_trading_day=is_trading_day,
            reason_code=reason,
            holiday_name=stored.holiday_name,
            source_code=stored.source_code or stored.source_type,
            session_type=stored.session_type,
            verified_status=stored.verified_status,
            regular_open_at=stored.regular_open_at,
            regular_close_at=stored.regular_close_at,
            timezone=stored.timezone or KRX_TIMEZONE,
            live_allowed=live_allowed,
        )

    def is_trading_day(
        self, exchange_code: str, calendar_date: date
    ) -> bool:
        return self.evaluate(
            exchange_code=exchange_code,
            calendar_date=calendar_date,
        ).is_trading_day

    def get_session(
        self, exchange_code: str, calendar_date: date
    ) -> TradingDayDecision:
        return self.evaluate(
            exchange_code=exchange_code,
            calendar_date=calendar_date,
        )

    def _aware(
        self, dt: datetime, tz_name: str = KRX_TIMEZONE
    ) -> datetime:
        tz = ZoneInfo(tz_name)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tz)
        return dt.astimezone(tz)

    def _resolve_timeline(
        self,
        exchange_code: str,
        calendar_date: date,
    ):
        """STEP 8-5-13 — 주입된 Repository 기준 Session Timeline 계산.

        (독립 DB Session을 새로 여는 session_timeline.resolve_for_exchange와
        달리, 이 Service가 보유한 Repository를 그대로 사용해 테스트에서도
        Fake Repository로 검증 가능하다.)
        """

        from stock_platform.operation.session_timeline import (
            TradingSessionTimelineResolver,
        )

        exchange = exchange_code.strip().upper()
        decision = self.evaluate(
            exchange_code=exchange, calendar_date=calendar_date
        )
        stored = self.get_calendar(exchange, calendar_date)
        revision = (
            int(getattr(stored, "revision", 0) or 0) if stored else 0
        )
        preopen = (
            getattr(stored, "preopen_at", None) if stored else None
        )
        resolver = TradingSessionTimelineResolver()
        return resolver.resolve_from_decision(
            exchange_code=exchange,
            market_date=calendar_date,
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

    def resolve_timeline(
        self,
        exchange_code: str,
        calendar_date: date,
    ):
        """STEP 8-5-13 — 외부(Admin/Health) 공개용 Timeline 조회."""

        return self._resolve_timeline(exchange_code, calendar_date)

    def is_regular_session(
        self, exchange_code: str, moment: datetime
    ) -> bool:
        """OPEN 또는 EXIT_ONLY(위험축소 전용) Phase 여부.

        신규 진입 가능 여부만 필요하면 allows_new_entry 계열을 사용한다.
        """

        from stock_platform.operation.session_timeline import (
            TradingSessionPhase,
        )

        local = self._aware(moment)
        timeline = self._resolve_timeline(exchange_code, local.date())
        phase = timeline.phase_at(local)
        return phase in {
            TradingSessionPhase.OPEN,
            TradingSessionPhase.EXIT_ONLY,
        }

    def is_preopen(
        self, exchange_code: str, moment: datetime
    ) -> bool:
        from stock_platform.operation.session_timeline import (
            TradingSessionPhase,
        )

        local = self._aware(moment)
        timeline = self._resolve_timeline(exchange_code, local.date())
        return timeline.phase_at(local) == TradingSessionPhase.PREOPEN

    def is_after_hours(
        self, exchange_code: str, moment: datetime
    ) -> bool:
        from stock_platform.operation.session_timeline import (
            TradingSessionPhase,
        )

        local = self._aware(moment)
        timeline = self._resolve_timeline(exchange_code, local.date())
        return timeline.phase_at(local) in {
            TradingSessionPhase.CLOSED,
            TradingSessionPhase.POST_CLOSE,
        }

    def require_trading_day(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
    ) -> TradingDayDecision:
        decision = self.evaluate(
            exchange_code=exchange_code,
            calendar_date=calendar_date,
        )
        if not decision.is_trading_day or not decision.live_allowed:
            detail = decision.holiday_name or decision.reason_code
            raise ValueError(
                f"Not a trading day: "
                f"{decision.exchange_code}/"
                f"{decision.calendar_date}/"
                f"{detail}"
            )
        return decision

    def require_live_order_session(
        self,
        *,
        exchange_code: str,
        moment: datetime | None = None,
        is_risk_reducing: bool = False,
    ) -> TradingDayDecision:
        """KRX LIVE 주문 전 Fail Closed 검사 (최신 Revision 우선).

        STEP 8-5-13 — Session Timeline Phase 기준으로 판단한다.
        EXIT_ONLY Phase에서는 is_risk_reducing=True인 주문만 허용한다.
        """

        exchange = exchange_code.strip().upper()
        if exchange in self.ALWAYS_OPEN_EXCHANGES:
            return self.evaluate(
                exchange_code=exchange,
                calendar_date=(moment or datetime.now(timezone.utc)).date(),
            )
        local = self._aware(
            moment or datetime.now(ZoneInfo(KRX_TIMEZONE))
        )
        # 짧은 TTL Cache — Apply 후 invalidate, 오래된 Cache로 주문 허용 금지
        try:
            from stock_platform.common.settings import get_settings
            from stock_platform.operation.calendar_cache import (
                cache_get,
                cache_set,
            )

            ttl = float(
                getattr(
                    get_settings(),
                    "krx_calendar_cache_ttl_seconds",
                    2.0,
                )
            )
            hit = cache_get(
                exchange_code=exchange,
                calendar_date=local.date(),
                ttl_seconds=ttl,
            )
            stored = self._repository.get_day(
                exchange_code=exchange,
                calendar_date=local.date(),
            )
            db_rev = int(getattr(stored, "revision", 0) or 0) if stored else 0
            if hit is not None:
                cached_rev, _ = hit
                if int(cached_rev) != db_rev:
                    # Revision 불일치 — Cache 폐기 후 DB 기준
                    from stock_platform.operation.calendar_cache import (
                        invalidate_calendar_cache,
                    )
                    from stock_platform.operation.session_timeline import (
                        invalidate_timeline_cache,
                    )

                    invalidate_calendar_cache(
                        exchange_code=exchange,
                        calendar_date=local.date(),
                    )
                    invalidate_timeline_cache(
                        exchange_code=exchange,
                        market_date=local.date(),
                    )
                else:
                    pass
            decision = self.evaluate(
                exchange_code=exchange,
                calendar_date=local.date(),
            )
            cache_set(
                exchange_code=exchange,
                calendar_date=local.date(),
                revision=db_rev,
                payload={"reason": decision.reason_code},
                ttl_seconds=ttl,
            )
        except Exception:  # noqa: BLE001
            decision = self.evaluate(
                exchange_code=exchange,
                calendar_date=local.date(),
            )
        if decision.reason_code in CALENDAR_UNAVAILABLE_REASONS:
            try:
                from stock_platform.operation.calendar_audit import (
                    audit_calendar_event,
                )

                audit_calendar_event(
                    "CALENDAR_LIVE_ORDER_BLOCKED",
                    detail={
                        "exchange_code": exchange,
                        "reason_code": decision.reason_code,
                        "calendar_date": local.date().isoformat(),
                    },
                )
            except Exception:  # noqa: BLE001
                pass
            raise ValueError(
                f"KRX calendar unavailable: {decision.reason_code}"
            )
        if not decision.is_trading_day:
            raise ValueError(
                f"KRX market closed: {decision.reason_code}"
            )

        from stock_platform.operation.session_timeline import (
            phase_reason_code,
        )

        timeline = self._resolve_timeline(exchange, local.date())
        if not timeline.allows_any_order(
            local, is_risk_reducing=is_risk_reducing
        ):
            phase = timeline.phase_at(local)
            raise ValueError(
                "KRX order outside regular session: "
                f"{phase_reason_code(phase)}"
            )
        return decision

    def previous_trading_day(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
        maximum_search_days: int = 30,
    ) -> date:
        return self._search(
            exchange_code=exchange_code,
            calendar_date=calendar_date,
            step=-1,
            maximum_search_days=maximum_search_days,
        )

    def next_trading_day(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
        maximum_search_days: int = 30,
    ) -> date:
        return self._search(
            exchange_code=exchange_code,
            calendar_date=calendar_date,
            step=1,
            maximum_search_days=maximum_search_days,
        )

    def _search(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
        step: int,
        maximum_search_days: int,
    ) -> date:
        if maximum_search_days <= 0:
            raise ValueError(
                "maximum_search_days must be greater than zero"
            )
        current = calendar_date
        for _ in range(maximum_search_days):
            current += timedelta(days=step)
            decision = self.evaluate(
                exchange_code=exchange_code,
                calendar_date=current,
            )
            if decision.is_trading_day and decision.live_allowed:
                return current
        raise LookupError(
            "Trading day was not found within search range"
        )

    def validate_calendar_coverage(
        self,
        exchange_code: str,
        from_date: date,
        to_date: date,
    ) -> CoverageReport:
        stats = self._repository.coverage_stats(
            exchange_code=exchange_code,
            from_date=from_date,
            to_date=to_date,
        )
        complete = bool(stats["coverage_complete"])
        live_ok = complete and stats["missing_days"] == 0
        message = (
            "Coverage OK"
            if live_ok
            else (
                f"Coverage incomplete: missing={stats['missing_days']} "
                f"verified={stats['by_verified_status']}"
            )
        )
        if not live_ok:
            try:
                from stock_platform.operation.calendar_audit import (
                    audit_calendar_event,
                )

                audit_calendar_event(
                    "CALENDAR_COVERAGE_INSUFFICIENT",
                    detail={
                        "exchange_code": exchange_code.upper(),
                        "from_date": from_date.isoformat(),
                        "to_date": to_date.isoformat(),
                        "missing_days": stats["missing_days"],
                    },
                )
            except Exception:  # noqa: BLE001
                pass
        return CoverageReport(
            exchange_code=exchange_code.upper(),
            from_date=from_date,
            to_date=to_date,
            expected_calendar_days=int(stats["expected_calendar_days"]),
            stored_days=int(stats["stored_days"]),
            missing_days=int(stats["missing_days"]),
            verified_trading_days=int(stats["verified_trading_days"]),
            coverage_complete=complete,
            by_verified_status=dict(stats["by_verified_status"]),
            live_trading_allowed=live_ok,
            message=message,
        )

    def user_status(
        self, exchange_code: str = "KRX"
    ) -> dict:
        """USER용 요약 (Source·검증자·Change Request 미포함)."""

        tz = ZoneInfo(KRX_TIMEZONE)
        today = datetime.now(tz).date()
        decision = self.evaluate(
            exchange_code=exchange_code,
            calendar_date=today,
        )
        next_day = None
        try:
            next_day = self.next_trading_day(
                exchange_code=exchange_code,
                calendar_date=today,
            )
        except LookupError:
            next_day = None
        unavailable = decision.reason_code in CALENDAR_UNAVAILABLE_REASONS
        stored = self.get_calendar(exchange_code, today)
        closure = (
            getattr(stored, "closure_reason", None) if stored else None
        )
        status_message = self._user_session_message(
            decision=decision,
            unavailable=unavailable,
            closure_reason=closure,
        )
        special = decision.session_type in {
            CalendarSessionType.DELAYED_OPEN.value,
            CalendarSessionType.EARLY_CLOSE.value,
            CalendarSessionType.SPECIAL_SESSION.value,
            CalendarSessionType.CLOSED.value,
        } or (not decision.is_trading_day and decision.live_allowed is False)

        # STEP 8-5-13 — Session Timeline Phase 기반 부가 정보
        # (내부 Job Key 등은 노출하지 않는다)
        exchange = exchange_code.strip().upper()
        now = datetime.now(tz)
        if exchange in self.ALWAYS_OPEN_EXCHANGES:
            phase_value = "OPEN"
            new_entry_cutoff_at = None
            next_transition_at = None
            next_transition_phase = None
            new_entry_allowed = True
            risk_reducing_allowed = True
        else:
            timeline = self._resolve_timeline(exchange, today)
            phase = timeline.phase_at(now)
            phase_value = phase.value
            new_entry_cutoff_at = (
                timeline.new_entry_cutoff_at.isoformat()
                if timeline.new_entry_cutoff_at
                else None
            )
            nxt_at, nxt_phase = timeline.next_transition(now)
            next_transition_at = nxt_at.isoformat() if nxt_at else None
            next_transition_phase = (
                nxt_phase.value if nxt_phase else None
            )
            new_entry_allowed = timeline.allows_new_entry(now)
            risk_reducing_allowed = timeline.allows_risk_reducing(now)

        # STEP 8-5-15 — 영속 Market Session Job 기반 소프트 상태
        # (Job ID 등 내부 식별자는 절대 노출하지 않고 boolean만 제공)
        snapshot_ready = False
        analysis_ready = False
        if exchange not in self.ALWAYS_OPEN_EXCHANGES:
            try:
                from stock_platform.operation.market_session_job_constants import (
                    MarketSessionJobType,
                )
                from stock_platform.operation.market_session_job_service import (
                    MarketSessionJobService,
                )

                job_svc = MarketSessionJobService(self._repository._session)
                snapshot_ready = job_svc.has_succeeded(
                    exchange_code=exchange,
                    market_date=today,
                    job_type=MarketSessionJobType.KRX_EQUITY_SNAPSHOT.value,
                )
                analysis_ready = job_svc.has_succeeded(
                    exchange_code=exchange,
                    market_date=today,
                    job_type=MarketSessionJobType.KRX_AI_ANALYSIS.value,
                )
            except Exception:  # noqa: BLE001
                snapshot_ready = False
                analysis_ready = False

        return {
            "exchange_code": exchange_code.upper(),
            "calendar_date": today.isoformat(),
            "is_trading_day": decision.is_trading_day
            and decision.live_allowed,
            "session_type": decision.session_type,
            "is_special_session": bool(special),
            "regular_open_at": (
                decision.regular_open_at.isoformat()
                if decision.regular_open_at
                else None
            ),
            "regular_close_at": (
                decision.regular_close_at.isoformat()
                if decision.regular_close_at
                else None
            ),
            "holiday_name": decision.holiday_name,
            "closure_reason": closure,
            "next_trading_day": (
                next_day.isoformat() if next_day else None
            ),
            "calendar_available": not unavailable,
            "status_message": status_message,
            # STEP 8-5-13 추가 필드
            "phase": phase_value,
            "new_entry_cutoff_at": new_entry_cutoff_at,
            "next_transition_at": next_transition_at,
            "next_transition_phase": next_transition_phase,
            "is_delayed_open": (
                decision.session_type
                == CalendarSessionType.DELAYED_OPEN.value
            ),
            "is_early_close": (
                decision.session_type
                == CalendarSessionType.EARLY_CLOSE.value
            ),
            "new_entry_allowed": bool(new_entry_allowed),
            "risk_reducing_allowed": bool(risk_reducing_allowed),
            # STEP 8-5-15 추가 필드 (소프트 상태, Job ID 미노출)
            "snapshot_ready": bool(snapshot_ready),
            "analysis_ready": bool(analysis_ready),
        }

    @staticmethod
    def _user_session_message(
        *,
        decision: TradingDayDecision,
        unavailable: bool,
        closure_reason: str | None,
    ) -> str:
        if unavailable:
            return "KRX 거래일 캘린더를 확인할 수 없습니다."
        open_s = (
            decision.regular_open_at.strftime("%H:%M")
            if decision.regular_open_at
            else None
        )
        close_s = (
            decision.regular_close_at.strftime("%H:%M")
            if decision.regular_close_at
            else None
        )
        st = decision.session_type
        if not decision.is_trading_day or st == CalendarSessionType.CLOSED.value:
            reason = (
                closure_reason
                or decision.holiday_name
                or "휴장"
            )
            return f"오늘은 한국거래소 휴장일입니다. ({reason})"
        if st == CalendarSessionType.DELAYED_OPEN.value and open_s:
            return f"오늘 KRX 정규장은 {open_s}에 시작합니다."
        if st == CalendarSessionType.EARLY_CLOSE.value and close_s:
            return f"오늘 KRX 정규장은 {close_s}에 종료됩니다."
        if st == CalendarSessionType.SPECIAL_SESSION.value:
            span = (
                f"{open_s}–{close_s}"
                if open_s and close_s
                else "특별 세션"
            )
            return f"오늘 KRX는 특별 거래시간({span})으로 운영됩니다."
        if open_s and close_s:
            return f"오늘 KRX 정규장 {open_s}–{close_s} 입니다."
        return decision.holiday_name or decision.reason_code
