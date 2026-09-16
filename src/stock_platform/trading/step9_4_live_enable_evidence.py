"""STEP 9-4 — STEP 9-3 LIVE Enable 증거 검증."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stock_platform.trading.step9_3_dry_run_evidence import (
    DryRunEvidenceError,
    report_content_hash,
)


def validate_step9_3_live_enable_evidence(
    report: dict[str, Any],
    *,
    expected_uba_id: int = 58,
    max_age_hours: float = 72.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise DryRunEvidenceError(
            "live_enable_missing", "STEP 9-3 report missing"
        )
    verdict = report.get("verdict")
    if verdict != "PASS_LIVE_ENABLED":
        raise DryRunEvidenceError(
            "live_enable_not_pass",
            f"STEP 9-3 verdict must be PASS_LIVE_ENABLED (got={verdict})",
        )
    after = (report.get("after") or {}).get("account") or {}
    before = (report.get("before") or {}).get("account") or {}
    uba = int(after.get("uba_id") or before.get("uba_id") or 0)
    if uba != int(expected_uba_id):
        raise DryRunEvidenceError(
            "live_enable_uba_mismatch",
            f"UBA mismatch: {uba} != {expected_uba_id}",
        )
    if after.get("live") is not True and report.get("mutations", {}).get(
        "live_on"
    ) != 1:
        # 리포트 after.live 가 true여야 함
        if after.get("live") is not True:
            raise DryRunEvidenceError(
                "live_enable_live_not_true",
                "STEP 9-3 after.live must be true",
            )
    if after.get("arm") is True:
        raise DryRunEvidenceError(
            "live_enable_arm_was_on",
            "STEP 9-3 must leave ARM=false",
        )
    audit = report.get("audit") or {}
    if not audit.get("id"):
        raise DryRunEvidenceError(
            "live_enable_audit_missing",
            "STEP 9-3 LIVE_APPROVED audit missing",
        )
    detail = audit.get("detail") or {}
    if detail.get("arm") is not False and detail.get("arm") is not None:
        # arm=false 기록
        if detail.get("arm") is True:
            raise DryRunEvidenceError(
                "live_enable_audit_arm_true",
                "LIVE Enable audit must record arm=false",
            )
    if not detail.get("correlation_id") and not report.get("correlation_id"):
        raise DryRunEvidenceError(
            "live_enable_correlation_missing",
            "STEP 9-3 correlation_id missing",
        )
    mut = report.get("mutations") or {}
    for key in (
        "arm_on",
        "create_order",
        "broker_submit",
        "db_order_insert",
    ):
        if int(mut.get(key) or 0) != 0:
            raise DryRunEvidenceError(
                "live_enable_mutation_nonzero",
                f"STEP 9-3 mutation {key} != 0",
            )

    checked_at = report.get("checked_at")
    if not checked_at:
        raise DryRunEvidenceError(
            "live_enable_timestamp_missing",
            "STEP 9-3 timestamp missing",
        )
    ts = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ref = now or datetime.now(timezone.utc)
    age_h = (ref - ts).total_seconds() / 3600.0
    if age_h > float(max_age_hours):
        raise DryRunEvidenceError(
            "live_enable_stale",
            f"STEP 9-3 evidence too old: {age_h:.1f}h",
        )
    return {
        "ok": True,
        "verdict": verdict,
        "uba_id": uba,
        "audit_id": audit.get("id"),
        "audit_event": audit.get("event_type"),
        "reason": detail.get("reason") or report.get("reason"),
        "correlation_id": detail.get("correlation_id")
        or report.get("correlation_id"),
        "checked_at": ts.isoformat(),
        "age_hours": round(age_h, 3),
        "report_hash": report.get("report_hash")
        or report_content_hash(report),
        "live_after": after.get("live"),
        "arm_after": after.get("arm"),
    }


def load_and_validate_live_enable_report(
    path: str | Path, **kwargs: Any
) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise DryRunEvidenceError(
            "live_enable_missing", f"STEP 9-3 report not found: {p}"
        )
    report = json.loads(p.read_text(encoding="utf-8"))
    evidence = validate_step9_3_live_enable_evidence(report, **kwargs)
    evidence["path"] = str(p)
    return evidence
