"""No-lookahead as-of helpers for market context research."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_no_lookahead(
    *,
    detected_at: datetime,
    context_timestamp: datetime | None,
    field: str,
) -> dict[str, Any]:
    """detected_at 이후 context 사용 금지. 위반 시 INVALID."""

    det = as_utc(detected_at)
    ctx = as_utc(context_timestamp)
    if det is None:
        return {"ok": False, "field": field, "reason": "MISSING_DETECTED_AT"}
    if ctx is None:
        return {"ok": False, "field": field, "reason": "MISSING_CONTEXT_TS"}
    if ctx > det:
        return {
            "ok": False,
            "field": field,
            "reason": "LOOKAHEAD_VIOLATION",
            "detected_at": det.isoformat(),
            "context_timestamp": ctx.isoformat(),
        }
    return {
        "ok": True,
        "field": field,
        "detected_at": det.isoformat(),
        "context_timestamp": ctx.isoformat(),
    }


def select_latest_as_of(
    rows: Sequence[dict[str, Any]],
    *,
    detected_at: datetime,
    ts_key: str = "source_timestamp",
) -> dict[str, Any] | None:
    """detected_at 이전(포함) 최신 snapshot 1건."""

    det = as_utc(detected_at)
    if det is None:
        return None
    eligible: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        ts = as_utc(row.get(ts_key) or row.get("observed_at"))
        if ts is None or ts > det:
            continue
        eligible.append((ts, row))
    if not eligible:
        return None
    eligible.sort(key=lambda x: x[0], reverse=True)
    return eligible[0][1]


def validate_bundle_no_lookahead(
    *,
    detected_at: datetime,
    parts: dict[str, datetime | None],
) -> dict[str, Any]:
    checks = {
        name: assert_no_lookahead(
            detected_at=detected_at,
            context_timestamp=ts,
            field=name,
        )
        for name, ts in parts.items()
        if ts is not None
    }
    violations = [c for c in checks.values() if not c.get("ok")]
    return {
        "ok": not violations,
        "checks": checks,
        "violations": violations,
        "context_as_of": as_utc(detected_at).isoformat() if as_utc(detected_at) else None,
    }
