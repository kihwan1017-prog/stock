"""Technical Shadow path quality — PURE computation (COV-A/C) + gate helpers (COV-B).

네트워크/DB/mutation 없음. Gate 판정 함수만 제공하며,
COMPLETED 전환은 evaluator가 호출한다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    MinuteBar,
    as_utc,
    floor_minute,
)

# evaluation_detail.path_quality.path_quality_version
# COV-C: full-window source absence evidence 반영 → v2
PATH_QUALITY_VERSION = "technical_path_quality_v2"


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return as_utc(dt).isoformat()


def expected_minute_slots(
    *,
    detected_at: datetime,
    end_at: datetime,
    now: datetime,
) -> list[datetime]:
    """detected floor … end floor 중 완료된 1m candle open 시각 목록.

    end_at 은 보통 min(now, detected+60m). 미래/미완료 분은 제외.
    """

    start = floor_minute(as_utc(detected_at))
    end = floor_minute(as_utc(end_at))
    now_utc = as_utc(now)
    if end < start:
        return []

    out: list[datetime] = []
    cursor = start
    while cursor <= end:
        # candle [cursor, cursor+1m) 가 끝나야 관측 대상
        if cursor + timedelta(minutes=1) <= now_utc:
            out.append(cursor)
        cursor = cursor + timedelta(minutes=1)
    return out


def _parse_absent_key(key: str | datetime) -> datetime | None:
    if isinstance(key, datetime):
        return floor_minute(as_utc(key))
    try:
        raw = str(key).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return floor_minute(as_utc(datetime.fromisoformat(raw)))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class PathQualityResult:
    """evaluation_detail.path_quality 직렬화용."""

    path_quality_version: str
    expected_minutes: int
    observed_candles: int
    source_absent_confirmed: int
    unresolved_missing: int
    coverage_ratio_raw: float | None
    coverage_ratio_resolved: float | None
    max_gap_minutes: int
    gap_count: int
    first_candle_at: str | None
    last_candle_at: str | None
    source_unavailable: bool
    sync_attempts: int
    sync_last_result: str | None
    defer_reason: str | None
    missing_range_count: int
    # COV-C provenance (optional / backward-compatible extras)
    source_check_performed: bool = False
    source_check_result: str | None = None
    source_candle_count: int = 0
    db_missing_source_present: int = 0
    source_reconcile_requests: int = 0

    def to_detail_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_path_quality(
    *,
    detected_at: datetime,
    end_at: datetime,
    now: datetime,
    bars: Sequence[MinuteBar],
    source_absent_confirmed_ats: Iterable[datetime] | None = None,
    source_unavailable: bool = False,
    sync_attempts: int = 0,
    sync_last_result: str | None = None,
    defer_reason: str | None = None,
    source_check_performed: bool = False,
    source_check_result: str | None = None,
    source_candle_count: int = 0,
    db_missing_source_present: int = 0,
    source_reconcile_requests: int = 0,
) -> PathQualityResult:
    """PURE path quality. synthetic candle 생성 없음."""

    expected = expected_minute_slots(
        detected_at=detected_at, end_at=end_at, now=now
    )
    expected_set = set(expected)
    expected_n = len(expected)

    observed_ats: set[datetime] = set()
    ordered_obs: list[datetime] = []
    for bar in bars:
        at = floor_minute(as_utc(bar.candle_at))
        if at in expected_set and at not in observed_ats:
            observed_ats.add(at)
            ordered_obs.append(at)
    ordered_obs.sort()
    observed_n = len(observed_ats)

    absent_ats: set[datetime] = set()
    for raw in source_absent_confirmed_ats or ():
        at = floor_minute(as_utc(raw))
        if at in expected_set and at not in observed_ats:
            absent_ats.add(at)
    absent_n = len(absent_ats)

    unresolved_ats = [
        t for t in expected if t not in observed_ats and t not in absent_ats
    ]
    unresolved_n = len(unresolved_ats)

    def _ratio(num: int) -> float | None:
        if expected_n <= 0:
            return None
        return round(num / expected_n, 6)

    # max consecutive expected minutes without OBSERVED bar (path hole)
    max_gap = 0
    gap_count = 0
    missing_range_count = 0
    run = 0
    in_gap = False
    for t in expected:
        if t not in observed_ats:
            run += 1
            max_gap = max(max_gap, run)
            if not in_gap:
                gap_count += 1
                missing_range_count += 1
                in_gap = True
        else:
            run = 0
            in_gap = False

    return PathQualityResult(
        path_quality_version=PATH_QUALITY_VERSION,
        expected_minutes=expected_n,
        observed_candles=observed_n,
        source_absent_confirmed=absent_n,
        unresolved_missing=unresolved_n,
        coverage_ratio_raw=_ratio(observed_n),
        coverage_ratio_resolved=_ratio(observed_n + absent_n),
        max_gap_minutes=max_gap,
        gap_count=gap_count,
        first_candle_at=_iso(ordered_obs[0] if ordered_obs else None),
        last_candle_at=_iso(ordered_obs[-1] if ordered_obs else None),
        source_unavailable=bool(source_unavailable),
        sync_attempts=max(0, int(sync_attempts)),
        sync_last_result=sync_last_result,
        defer_reason=defer_reason,
        missing_range_count=missing_range_count,
        source_check_performed=bool(source_check_performed),
        source_check_result=source_check_result,
        source_candle_count=int(source_candle_count),
        db_missing_source_present=int(db_missing_source_present),
        source_reconcile_requests=int(source_reconcile_requests),
    )


def path_completeness_pass(path_quality: Mapping[str, Any] | PathQualityResult | None) -> bool:
    """COV-B production gate predicate.

    unresolved_missing == 0 AND source_unavailable == false
    """

    if path_quality is None:
        return False
    if isinstance(path_quality, PathQualityResult):
        return (
            int(path_quality.unresolved_missing) == 0
            and not bool(path_quality.source_unavailable)
        )
    unresolved = int(path_quality.get("unresolved_missing") or 0)
    unavailable = bool(path_quality.get("source_unavailable"))
    return unresolved == 0 and not unavailable


def path_defer_reasons(
    path_quality: Mapping[str, Any] | PathQualityResult | None,
) -> list[str]:
    """DEFER reason codes (structured, no schema migration)."""

    if path_quality is None:
        return ["PATH_QUALITY_MISSING"]
    if isinstance(path_quality, PathQualityResult):
        unresolved = int(path_quality.unresolved_missing)
        unavailable = bool(path_quality.source_unavailable)
    else:
        unresolved = int(path_quality.get("unresolved_missing") or 0)
        unavailable = bool(path_quality.get("source_unavailable"))
    reasons: list[str] = []
    if unavailable:
        reasons.append("SOURCE_UNAVAILABLE")
    if unresolved > 0:
        reasons.append("PATH_UNRESOLVED_MISSING")
    if not reasons:
        reasons.append("PATH_INCOMPLETE")
    return reasons


def build_path_defer_detail(
    *,
    path_quality: Mapping[str, Any] | None,
    previous: Mapping[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    """ACTIVE defer provenance — evaluation_detail.path_defer."""

    reasons = path_defer_reasons(path_quality)
    prev = dict(previous or {})
    first = prev.get("first_deferred_at") or as_utc(now).isoformat()
    try:
        first_dt = as_utc(datetime.fromisoformat(str(first).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        first_dt = as_utc(now)
        first = first_dt.isoformat()
    defer_count = int(prev.get("defer_count") or 0) + 1
    now_utc = as_utc(now)
    return {
        "defer_reason": reasons[0] if len(reasons) == 1 else "PATH_INCOMPLETE",
        "defer_reasons": reasons,
        "defer_count": defer_count,
        "first_deferred_at": first,
        "last_deferred_at": now_utc.isoformat(),
        "defer_age_seconds": int((now_utc - first_dt).total_seconds()),
        "path_quality_version": (
            (path_quality or {}).get("path_quality_version")
            if isinstance(path_quality, Mapping)
            else PATH_QUALITY_VERSION
        ),
        "unresolved_missing": (
            (path_quality or {}).get("unresolved_missing")
            if isinstance(path_quality, Mapping)
            else None
        ),
        "source_unavailable": (
            bool((path_quality or {}).get("source_unavailable"))
            if isinstance(path_quality, Mapping)
            else None
        ),
    }



def absent_ats_from_target_map(
    absent_by_target: Mapping[str, Any] | None,
) -> set[datetime]:
    """resolve_missing_target_minutes.absent_by_target → confirmed absences."""

    out: set[datetime] = set()
    for key, flag in (absent_by_target or {}).items():
        if not flag:
            continue
        parsed = _parse_absent_key(key)
        if parsed is not None:
            out.add(parsed)
    return out


def source_unavailable_from_maps(
    *,
    source_unavailable_by_target: Mapping[str, Any] | None = None,
    sync_payload: Any = None,
) -> tuple[bool, str | None]:
    """target resolve / soft-sync evidence → (unavailable, last_result)."""

    if any(bool(v) for v in (source_unavailable_by_target or {}).values()):
        return True, "TARGET_SOURCE_UNAVAILABLE"

    if sync_payload is None:
        return False, None

    if isinstance(sync_payload, dict):
        if sync_payload.get("ok") is False:
            err = sync_payload.get("error")
            return True, f"SYNC_FAILED:{err or 'unknown'}"
        if sync_payload.get("ok") is True:
            return False, "SYNC_OK"
        # UpbitMinuteSyncResult 직렬화 형태 등
        if "saved_count" in sync_payload or "collected_count" in sync_payload:
            return False, "SYNC_RESULT"

    # dataclass-like
    if hasattr(sync_payload, "saved_count"):
        return False, "SYNC_RESULT"

    return False, "SYNC_PRESENT"
