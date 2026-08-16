"""Shadow LONG_ACTIVE permanent-absence termination (TARGET_ONLY).

SOURCE_UNAVAILABLE_MAX_AGE 는 범위 밖 — unavailable 이면 ACTIVE retry 유지.
스키마/마이그레이션 없음. evaluation_detail JSON 만 사용.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    DEFAULT_MAX_PRIOR_LAG_SECONDS,
    FALLBACK_ABSENT_CONFIRMED,
    as_utc,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_ACTIVE,
    SHADOW_STATUS_CANCELLED,
)

TERMINATION_VERSION = "shadow_termination_v1"
TERMINATION_REASON_TARGET = "TARGET_PERMANENTLY_UNRESOLVABLE"
TARGET_WINDOW_MINUTES = 60


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return as_utc(value)
    if isinstance(value, str) and value.strip():
        try:
            return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def grace_seconds(*, interval_seconds: float | None = None) -> float:
    """3 × evaluator interval (default 540s)."""

    if interval_seconds is None:
        settings = get_settings()
        interval_seconds = float(
            getattr(
                settings,
                "upbit_scanner_shadow_evaluator_interval_seconds",
                180.0,
            )
            or 180.0
        )
    return 3.0 * float(interval_seconds)


def _window_60(computed: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    windows = computed.get("windows") or detail.get("windows") or {}
    return dict(windows.get("60") or windows.get(60) or {})


def _prior_lag_seconds(window60: dict[str, Any]) -> float | None:
    lag = window60.get("lag_seconds")
    if lag is not None:
        try:
            return float(lag)
        except (TypeError, ValueError):
            return None
    return None


def _source_absent_confirmed(
    window60: dict[str, Any],
    *,
    computed: dict[str, Any],
    detail: dict[str, Any],
) -> bool:
    if window60.get("fallback_reason") == FALLBACK_ABSENT_CONFIRMED:
        return True
    target_start = window60.get("target_candle_start")
    resolve = computed.get("target_resolve") or detail.get("target_resolve") or {}
    if target_start and isinstance(resolve, dict):
        entry = resolve.get(str(target_start)) or resolve.get(target_start)
        if isinstance(entry, dict):
            return entry.get("status") == FALLBACK_ABSENT_CONFIRMED
    return False


def _path_ok(path_quality: dict[str, Any] | None) -> bool:
    if not isinstance(path_quality, dict):
        return False
    if path_quality.get("source_unavailable") is True:
        return False
    try:
        unresolved = int(path_quality.get("unresolved_missing") or 0)
    except (TypeError, ValueError):
        return False
    if unresolved != 0:
        return False
    # reconcile OK: check performed 또는 source_check_result OK
    reconcile = path_quality.get("source_reconcile")
    if isinstance(reconcile, dict):
        if reconcile.get("source_unavailable") is True:
            return False
        if reconcile.get("source_check_performed") is True:
            return True
        if str(reconcile.get("source_check_result") or "").upper() == "OK":
            return True
    if path_quality.get("source_check_performed") is True:
        return True
    if str(path_quality.get("source_check_result") or "").upper() == "OK":
        return True
    return False


def is_permanent_absence_candidate(
    *,
    status: str,
    computed: dict[str, Any],
    detail: dict[str, Any],
    now: datetime,
    max_prior_lag_seconds: float = DEFAULT_MAX_PRIOR_LAG_SECONDS,
) -> dict[str, Any]:
    """grace 제외 permanent-absence 후보 여부 + evidence."""

    evidence: dict[str, Any] = {
        "candidate": False,
        "reason_blocked": None,
    }
    if status != SHADOW_STATUS_ACTIVE:
        evidence["reason_blocked"] = "NOT_ACTIVE"
        return evidence

    path_quality = computed.get("path_quality")
    if isinstance(path_quality, dict) and path_quality.get("source_unavailable"):
        evidence["reason_blocked"] = "SOURCE_UNAVAILABLE"
        return evidence

    window60 = _window_60(computed, detail)
    if not window60:
        evidence["reason_blocked"] = "NO_WINDOW_60"
        return evidence

    if str(window60.get("status") or "") != "MISSING_CANDLE":
        evidence["reason_blocked"] = "WINDOW_NOT_MISSING"
        return evidence

    candle_end = _parse_iso(window60.get("target_candle_end"))
    if candle_end is None or as_utc(now) < candle_end:
        evidence["reason_blocked"] = "NOT_MATURE"
        return evidence

    if not _source_absent_confirmed(window60, computed=computed, detail=detail):
        evidence["reason_blocked"] = "ABSENT_NOT_CONFIRMED"
        return evidence

    if not _path_ok(path_quality if isinstance(path_quality, dict) else None):
        evidence["reason_blocked"] = "PATH_NOT_OK"
        return evidence

    lag = _prior_lag_seconds(window60)
    # MISSING 이고 ABSENT_CONFIRMED 인데 lag 미기재면 prior 없음으로 취급(> limit)
    if lag is not None and lag <= float(max_prior_lag_seconds):
        evidence["reason_blocked"] = "PRIOR_WITHIN_FALLBACK"
        evidence["prior_lag_seconds"] = lag
        return evidence

    evidence.update(
        {
            "candidate": True,
            "target_at": window60.get("target_at"),
            "target_candle_end": window60.get("target_candle_end"),
            "nearest_prior_at": window60.get("observed_candle_at"),
            "prior_lag_seconds": lag,
            "fallback_limit_seconds": float(max_prior_lag_seconds),
        }
    )
    return evidence


def resolve_first_blocked_at(
    detail: dict[str, Any],
    *,
    candidate: dict[str, Any],
    now: datetime,
) -> datetime:
    """기존 first_blocked_at 유지 · 없으면 60m candle_end bootstrap."""

    term = detail.get("termination")
    if isinstance(term, dict) and term.get("terminated_at"):
        # 이미 종료된 행 — caller가 status로 막아야 함
        existing = _parse_iso(term.get("first_blocked_at"))
        if existing is not None:
            return existing

    cand_block = detail.get("termination_candidate")
    if isinstance(cand_block, dict):
        existing = _parse_iso(cand_block.get("first_blocked_at"))
        if existing is not None:
            return existing

    if isinstance(term, dict):
        existing = _parse_iso(term.get("first_blocked_at"))
        if existing is not None:
            return existing

    bootstrap = _parse_iso(candidate.get("target_candle_end"))
    if bootstrap is not None:
        return bootstrap
    return as_utc(now)


def grace_elapsed(
    *,
    first_blocked_at: datetime,
    now: datetime,
    interval_seconds: float | None = None,
) -> bool:
    return as_utc(now) >= as_utc(first_blocked_at) + timedelta(
        seconds=grace_seconds(interval_seconds=interval_seconds)
    )


def build_termination_detail(
    *,
    candidate: dict[str, Any],
    first_blocked_at: datetime,
    now: datetime,
) -> dict[str, Any]:
    return {
        "version": TERMINATION_VERSION,
        "reason": TERMINATION_REASON_TARGET,
        "terminated_at": as_utc(now).isoformat(),
        "target_window": TARGET_WINDOW_MINUTES,
        "target_at": candidate.get("target_at"),
        "nearest_prior_at": candidate.get("nearest_prior_at"),
        "prior_lag_seconds": candidate.get("prior_lag_seconds"),
        "fallback_limit_seconds": candidate.get("fallback_limit_seconds"),
        "first_blocked_at": as_utc(first_blocked_at).isoformat(),
        "last_checked_at": as_utc(now).isoformat(),
    }


def apply_permanent_absence_termination(
    row: Any,
    *,
    computed: dict[str, Any],
    now: datetime,
    interval_seconds: float | None = None,
    max_prior_lag_seconds: float = DEFAULT_MAX_PRIOR_LAG_SECONDS,
) -> dict[str, Any]:
    """ACTIVE row에 대해 CANCELLED 전환 또는 first_blocked_at 기록.

    Returns:
        changed / terminated / deferred_grace
    """

    detail = dict(getattr(row, "evaluation_detail", None) or {})

    # idempotent: 이미 CANCELLED 또는 termination 기록
    existing_term = detail.get("termination")
    if getattr(row, "status", None) == SHADOW_STATUS_CANCELLED:
        return {"changed": False, "terminated": False, "already_cancelled": True}
    if isinstance(existing_term, dict) and existing_term.get("terminated_at"):
        return {"changed": False, "terminated": False, "already_terminated": True}

    candidate = is_permanent_absence_candidate(
        status=str(getattr(row, "status", "") or ""),
        computed=computed,
        detail=detail,
        now=now,
        max_prior_lag_seconds=max_prior_lag_seconds,
    )
    if not candidate.get("candidate"):
        return {
            "changed": False,
            "terminated": False,
            "reason_blocked": candidate.get("reason_blocked"),
        }

    first_blocked = resolve_first_blocked_at(detail, candidate=candidate, now=now)
    # grace 대기 중이면 candidate 스탬프만 (first-write)
    cand_prev = (
        detail.get("termination_candidate")
        if isinstance(detail.get("termination_candidate"), dict)
        else {}
    )
    if not grace_elapsed(
        first_blocked_at=first_blocked,
        now=now,
        interval_seconds=interval_seconds,
    ):
        new_cand = {
            **cand_prev,
            "reason": TERMINATION_REASON_TARGET,
            "first_blocked_at": as_utc(first_blocked).isoformat(),
            "last_checked_at": as_utc(now).isoformat(),
            "prior_lag_seconds": candidate.get("prior_lag_seconds"),
            "fallback_limit_seconds": candidate.get("fallback_limit_seconds"),
        }
        if new_cand != cand_prev:
            detail["termination_candidate"] = new_cand
            row.evaluation_detail = detail
            row.updated_at = now
            return {
                "changed": True,
                "terminated": False,
                "deferred_grace": True,
                "first_blocked_at": new_cand["first_blocked_at"],
            }
        return {
            "changed": False,
            "terminated": False,
            "deferred_grace": True,
            "first_blocked_at": as_utc(first_blocked).isoformat(),
        }

    # terminal write — fake metric 금지
    term = build_termination_detail(
        candidate=candidate,
        first_blocked_at=first_blocked,
        now=now,
    )
    detail["termination"] = term
    detail.pop("termination_candidate", None)
    row.evaluation_detail = detail
    row.status = SHADOW_STATUS_CANCELLED
    row.updated_at = now
    return {
        "changed": True,
        "terminated": True,
        "reason": TERMINATION_REASON_TARGET,
        "termination": term,
    }
