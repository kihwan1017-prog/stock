"""Shadow 시계열 평가 — minute candle 선택·MFE/MAE·TP/SL 중앙 정책."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def floor_minute(value: datetime) -> datetime:
    dt = as_utc(value)
    return dt.replace(second=0, microsecond=0)


def return_pct(entry: Decimal, price: Decimal) -> Decimal:
    """(price - entry) / entry * 100."""

    if entry <= 0:
        return Decimal("0")
    return (price - entry) / entry * Decimal("100")


@dataclass(frozen=True, slots=True)
class MinuteBar:
    candle_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    def is_completed(self, *, now: datetime, timeframe_minutes: int = 1) -> bool:
        end = as_utc(self.candle_at) + timedelta(minutes=timeframe_minutes)
        return end <= as_utc(now)


@dataclass(frozen=True, slots=True)
class WindowObservation:
    minutes: int
    target_at: datetime
    observed_candle_at: datetime | None
    price: Decimal | None
    return_pct: Decimal | None
    status: str  # OK | NOT_MATURED | MISSING_CANDLE | SOURCE_UNAVAILABLE | FUTURE_BLOCKED
    target_candle_start: datetime | None = None
    target_candle_end: datetime | None = None
    final: bool = False
    selection_type: str | None = None
    lag_seconds: float | None = None
    fallback_reason: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class FinalWindowSelection:
    """FINAL window 선택 결과 — synthetic candle 없음."""

    bar: MinuteBar | None
    status: str
    selection_type: str | None = None
    lag_seconds: float | None = None
    fallback_reason: str | None = None
    source: str | None = None


# LAST_KNOWN_PRICE_AT_TARGET 정책 상수
SELECTION_EXACT = "EXACT_TARGET_CANDLE"
SELECTION_LAST_KNOWN = "LAST_KNOWN_BEFORE_TARGET"
FALLBACK_ABSENT_CONFIRMED = "TARGET_CANDLE_ABSENT_CONFIRMED"
DEFAULT_MAX_PRIOR_LAG_SECONDS = 180


@dataclass(frozen=True, slots=True)
class TpSlResult:
    tp_hit: bool
    sl_hit: bool
    tp_hit_at: datetime | None
    sl_hit_at: datetime | None
    first_hit: str | None  # TP | SL | SAME_CANDLE_SL_CONSERVATIVE | None
    detail: dict[str, Any]


def target_candle_bounds(
    target_at: datetime,
    *,
    timeframe_minutes: int = 1,
) -> tuple[datetime, datetime]:
    """target 이 속한 1m candle [start, end)."""

    start = floor_minute(target_at)
    end = start + timedelta(minutes=int(timeframe_minutes))
    return start, end


def _find_exact_bar(
    bars: Sequence[MinuteBar],
    *,
    candle_start: datetime,
) -> MinuteBar | None:
    start = as_utc(candle_start)
    for bar in bars:
        if as_utc(bar.candle_at) == start:
            return bar
    return None


def _find_last_known_before(
    bars: Sequence[MinuteBar],
    *,
    candle_start: datetime,
    now: datetime,
    timeframe_minutes: int,
    max_prior_lag_seconds: int,
) -> tuple[MinuteBar | None, float | None]:
    """target candle start 이전 최신 completed candle (lag 상한)."""

    start = as_utc(candle_start)
    now_utc = as_utc(now)
    eligible: list[MinuteBar] = []
    for bar in bars:
        at = as_utc(bar.candle_at)
        if at >= start:
            continue
        if not bar.is_completed(
            now=now_utc, timeframe_minutes=timeframe_minutes
        ):
            continue
        lag = (start - at).total_seconds()
        if lag > float(max_prior_lag_seconds):
            continue
        eligible.append(bar)
    if not eligible:
        return None, None
    chosen = max(eligible, key=lambda b: as_utc(b.candle_at))
    lag_seconds = (start - as_utc(chosen.candle_at)).total_seconds()
    return chosen, float(lag_seconds)


def select_final_window_close(
    bars: Sequence[MinuteBar],
    *,
    target_at: datetime,
    now: datetime,
    timeframe_minutes: int = 1,
    max_prior_lag_seconds: int = DEFAULT_MAX_PRIOR_LAG_SECONDS,
    target_absent_confirmed: bool = False,
    source_unavailable: bool = False,
    candle_source: str = "market.candle_minute",
) -> FinalWindowSelection:
    """FINAL window — candle close 이후 exact, 없으면 확인된 no-trade gap fallback.

    race fix 유지: now < target_candle_end 이면 prior 있어도 FINAL 금지.
    """

    target = as_utc(target_at)
    now_utc = as_utc(now)
    candle_start, candle_end = target_candle_bounds(
        target, timeframe_minutes=timeframe_minutes
    )

    if now_utc < candle_end:
        return FinalWindowSelection(
            bar=None,
            status="NOT_MATURED",
            selection_type=None,
            lag_seconds=None,
            fallback_reason=None,
            source=None,
        )

    exact = _find_exact_bar(bars, candle_start=candle_start)
    if exact is not None:
        if not exact.is_completed(
            now=now_utc, timeframe_minutes=timeframe_minutes
        ):
            return FinalWindowSelection(None, "NOT_MATURED")
        if as_utc(exact.candle_at) > now_utc:
            return FinalWindowSelection(None, "FUTURE_BLOCKED")
        return FinalWindowSelection(
            bar=exact,
            status="OK",
            selection_type=SELECTION_EXACT,
            lag_seconds=(target - as_utc(exact.candle_at)).total_seconds(),
            fallback_reason=None,
            source=candle_source,
        )

    # exact 없음
    if source_unavailable:
        return FinalWindowSelection(
            bar=None,
            status="SOURCE_UNAVAILABLE",
            selection_type=None,
            lag_seconds=None,
            fallback_reason="SOURCE_UNAVAILABLE",
            source=None,
        )

    if not target_absent_confirmed:
        # sync/API 재확인 전 — fallback FINAL 금지
        return FinalWindowSelection(
            bar=None,
            status="MISSING_CANDLE",
            selection_type=None,
            lag_seconds=None,
            fallback_reason=None,
            source=None,
        )

    prior, lag = _find_last_known_before(
        bars,
        candle_start=candle_start,
        now=now_utc,
        timeframe_minutes=timeframe_minutes,
        max_prior_lag_seconds=int(max_prior_lag_seconds),
    )
    if prior is None:
        return FinalWindowSelection(
            bar=None,
            status="MISSING_CANDLE",
            selection_type=None,
            lag_seconds=lag,
            fallback_reason=FALLBACK_ABSENT_CONFIRMED,
            source=None,
        )
    return FinalWindowSelection(
        bar=prior,
        status="OK",
        selection_type=SELECTION_LAST_KNOWN,
        lag_seconds=lag,
        fallback_reason=FALLBACK_ABSENT_CONFIRMED,
        source=candle_source,
    )


def select_close_at_or_before(
    bars: Sequence[MinuteBar],
    *,
    target_at: datetime,
    now: datetime,
    timeframe_minutes: int = 1,
    max_lag_minutes: int = 3,
) -> tuple[MinuteBar | None, str]:
    """PREVIEW/provisional — target 이하 최신 completed candle.

    final column stamp 에는 사용하지 않는다.
    """

    target = as_utc(target_at)
    now_utc = as_utc(now)
    if target > now_utc:
        return None, "NOT_MATURED"

    eligible: list[MinuteBar] = []
    for bar in bars:
        at = as_utc(bar.candle_at)
        if at > target:
            continue
        if not bar.is_completed(now=now_utc, timeframe_minutes=timeframe_minutes):
            continue
        if at > now_utc:
            continue
        eligible.append(bar)

    if not eligible:
        return None, "MISSING_CANDLE"

    chosen = max(eligible, key=lambda b: as_utc(b.candle_at))
    lag = (target - as_utc(chosen.candle_at)).total_seconds() / 60.0
    if lag > float(max_lag_minutes):
        return None, "MISSING_CANDLE"
    return chosen, "OK"


def observe_windows(
    bars: Sequence[MinuteBar],
    *,
    detected_at: datetime,
    entry: Decimal,
    now: datetime,
    windows_minutes: Sequence[int],
    timeframe_minutes: int = 1,
    max_lag_minutes: int = 3,
    max_prior_lag_seconds: int = DEFAULT_MAX_PRIOR_LAG_SECONDS,
    absent_by_target: dict[str, bool] | None = None,
    source_unavailable_by_target: dict[str, bool] | None = None,
    candle_source: str = "market.candle_minute",
) -> list[WindowObservation]:
    """FINAL window observations — LAST_KNOWN_PRICE_AT_TARGET 정책."""

    del max_lag_minutes  # provisional helper 호환 파라미터
    absent_by_target = absent_by_target or {}
    source_unavailable_by_target = source_unavailable_by_target or {}
    out: list[WindowObservation] = []
    t0 = as_utc(detected_at)
    for minutes in windows_minutes:
        target = t0 + timedelta(minutes=int(minutes))
        candle_start, candle_end = target_candle_bounds(
            target, timeframe_minutes=timeframe_minutes
        )
        key = candle_start.isoformat()
        selection = select_final_window_close(
            bars,
            target_at=target,
            now=now,
            timeframe_minutes=timeframe_minutes,
            max_prior_lag_seconds=max_prior_lag_seconds,
            target_absent_confirmed=bool(absent_by_target.get(key, False)),
            source_unavailable=bool(
                source_unavailable_by_target.get(key, False)
            ),
            candle_source=candle_source,
        )
        if selection.bar is None:
            out.append(
                WindowObservation(
                    minutes=int(minutes),
                    target_at=target,
                    observed_candle_at=None,
                    price=None,
                    return_pct=None,
                    status=selection.status,
                    target_candle_start=candle_start,
                    target_candle_end=candle_end,
                    final=False,
                    selection_type=selection.selection_type,
                    lag_seconds=selection.lag_seconds,
                    fallback_reason=selection.fallback_reason,
                    source=selection.source,
                )
            )
            continue
        price = selection.bar.close
        out.append(
            WindowObservation(
                minutes=int(minutes),
                target_at=target,
                observed_candle_at=as_utc(selection.bar.candle_at),
                price=price,
                return_pct=return_pct(entry, price),
                status="OK",
                target_candle_start=candle_start,
                target_candle_end=candle_end,
                final=True,
                selection_type=selection.selection_type,
                lag_seconds=selection.lag_seconds,
                fallback_reason=selection.fallback_reason,
                source=selection.source,
            )
        )
    return out


def compute_mfe_mae(
    bars: Sequence[MinuteBar],
    *,
    entry: Decimal,
    start_at: datetime,
    end_at: datetime,
    now: datetime,
    timeframe_minutes: int = 1,
) -> tuple[Decimal | None, Decimal | None, dict[str, Any]]:
    """Long: MFE=max(high) excursion, MAE=min(low) excursion."""

    if entry <= 0:
        return None, None, {"reason": "INVALID_ENTRY"}

    start = as_utc(start_at)
    end = as_utc(end_at)
    now_utc = as_utc(now)
    highs: list[Decimal] = []
    lows: list[Decimal] = []
    used = 0
    for bar in bars:
        at = as_utc(bar.candle_at)
        if at < floor_minute(start):
            continue
        if at > end:
            continue
        if not bar.is_completed(now=now_utc, timeframe_minutes=timeframe_minutes):
            continue
        highs.append(bar.high)
        lows.append(bar.low)
        used += 1

    if not highs or not lows:
        return None, None, {"reason": "NO_BARS", "used": 0}

    max_high = max(highs)
    min_low = min(lows)
    mfe = return_pct(entry, max_high)
    mae = return_pct(entry, min_low)
    return (
        mfe,
        mae,
        {
            "used": used,
            "max_high": float(max_high),
            "min_low": float(min_low),
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
        },
    )


def compute_tp_sl(
    bars: Sequence[MinuteBar],
    *,
    entry: Decimal,
    start_at: datetime,
    end_at: datetime,
    now: datetime,
    tp_pct: float,
    sl_pct: float,
    timeframe_minutes: int = 1,
) -> TpSlResult:
    """1m high/low 경로로 TP/SL. 동일 candle 동시 → SL 우선(Fail Conservative)."""

    if entry <= 0:
        return TpSlResult(False, False, None, None, None, {"reason": "INVALID_ENTRY"})

    tp_price = entry * (Decimal("1") + Decimal(str(abs(tp_pct))) / Decimal("100"))
    sl_price = entry * (Decimal("1") - Decimal(str(abs(sl_pct))) / Decimal("100"))
    start = floor_minute(as_utc(start_at))
    end = as_utc(end_at)
    now_utc = as_utc(now)

    tp_hit = False
    sl_hit = False
    tp_at: datetime | None = None
    sl_at: datetime | None = None
    first: str | None = None

    ordered = sorted(
        (
            b
            for b in bars
            if start <= as_utc(b.candle_at) <= end
            and b.is_completed(now=now_utc, timeframe_minutes=timeframe_minutes)
        ),
        key=lambda b: as_utc(b.candle_at),
    )

    for bar in ordered:
        hit_tp = bar.high >= tp_price
        hit_sl = bar.low <= sl_price
        at = as_utc(bar.candle_at)
        if hit_tp and hit_sl:
            # Fail Conservative — 동일 분봉에서 둘 다 터치 시 SL 우선
            if not sl_hit:
                sl_hit = True
                sl_at = at
            if not tp_hit:
                tp_hit = True
                tp_at = at
            if first is None:
                first = "SAME_CANDLE_SL_CONSERVATIVE"
            break
        if hit_sl and not sl_hit:
            sl_hit = True
            sl_at = at
            if first is None:
                first = "SL"
        if hit_tp and not tp_hit:
            tp_hit = True
            tp_at = at
            if first is None:
                first = "TP"
        if tp_hit and sl_hit:
            break

    return TpSlResult(
        tp_hit=tp_hit,
        sl_hit=sl_hit,
        tp_hit_at=tp_at,
        sl_hit_at=sl_at,
        first_hit=first,
        detail={
            "tp_price": float(tp_price),
            "sl_price": float(sl_price),
            "bars_checked": len(ordered),
            "policy": "SAME_CANDLE_SL_CONSERVATIVE",
        },
    )


def bars_from_rows(rows: Sequence[Any]) -> list[MinuteBar]:
    """ORM CandleMinute / dict → MinuteBar."""

    out: list[MinuteBar] = []
    for row in rows:
        if isinstance(row, dict):
            at = row.get("candle_at")
            o = row.get("open_price")
            h = row.get("high_price")
            low = row.get("low_price")
            c = row.get("close_price")
        else:
            at = getattr(row, "candle_at", None)
            o = getattr(row, "open_price", None)
            h = getattr(row, "high_price", None)
            low = getattr(row, "low_price", None)
            c = getattr(row, "close_price", None)
        if at is None or c is None or h is None or low is None or o is None:
            continue
        out.append(
            MinuteBar(
                candle_at=as_utc(at),
                open=Decimal(str(o)),
                high=Decimal(str(h)),
                low=Decimal(str(low)),
                close=Decimal(str(c)),
            )
        )
    out.sort(key=lambda b: b.candle_at)
    return out
