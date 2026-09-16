"""STEP 9-3 — Dry Run 증거 검증 (LIVE Enable 직전)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DryRunEvidenceError(ValueError):
    """Dry Run 증거 불일치/만료."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def report_content_hash(payload: dict[str, Any] | str | bytes) -> str:
    if isinstance(payload, dict):
        raw = json.dumps(payload, sort_keys=True, default=str).encode(
            "utf-8"
        )
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = payload
    return hashlib.sha256(raw).hexdigest()


def validate_step9_2_dry_run_evidence(
    report: dict[str, Any],
    *,
    expected_uba_id: int = 58,
    expected_market: str = "KRW-BTC",
    expected_amount: str | int = 5000,
    max_age_hours: float = 72.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """STEP 9-2 PASS_DRY_RUN 증거가 LIVE Enable에 유효한지 검증."""
    if not isinstance(report, dict):
        raise DryRunEvidenceError(
            "dry_run_missing", "Dry Run report missing"
        )

    dry = report.get("dry_run") or {}
    verdict = (
        dry.get("verdict")
        or report.get("verdict")
        or report.get("result")
    )
    if verdict != "PASS_DRY_RUN":
        raise DryRunEvidenceError(
            "dry_run_not_pass",
            f"Dry Run verdict must be PASS_DRY_RUN (got={verdict})",
        )

    account = (report.get("precheck") or {}).get("account") or {}
    uba = int(
        account.get("uba_id")
        or dry.get("uba_id")
        or report.get("uba_id")
        or 0
    )
    if uba != int(expected_uba_id):
        raise DryRunEvidenceError(
            "dry_run_uba_mismatch",
            f"Dry Run UBA mismatch: {uba} != {expected_uba_id}",
        )

    market = str(
        dry.get("market")
        or (report.get("precheck") or {}).get("market_arg")
        or ""
    ).upper()
    if market != str(expected_market).upper():
        raise DryRunEvidenceError(
            "dry_run_market_mismatch",
            f"Dry Run market mismatch: {market} != {expected_market}",
        )

    amount_raw = dry.get("requested_amount") or report.get(
        "requested_amount"
    )
    try:
        amount_ok = int(Decimal_like(amount_raw)) == int(expected_amount)
    except Exception as exc:  # noqa: BLE001
        raise DryRunEvidenceError(
            "dry_run_amount_invalid",
            f"Dry Run amount invalid: {amount_raw}",
        ) from exc
    if not amount_ok:
        raise DryRunEvidenceError(
            "dry_run_amount_mismatch",
            f"Dry Run amount mismatch: {amount_raw} != {expected_amount}",
        )

    mutations = report.get("mutations") or {}
    for key in (
        "create_order",
        "cancel_order",
        "replace_order",
        "live_on",
        "arm_on",
    ):
        if int(mutations.get(key) or 0) != 0:
            raise DryRunEvidenceError(
                "dry_run_mutation_nonzero",
                f"Dry Run mutation {key} != 0",
            )

    # Broker submit / DB insert — 리포트 필드명 호환
    deltas = dry.get("deltas") or report.get("deltas") or {}
    for key in (
        "broker_submit",
        "db_order_insert",
        "execution_insert",
        "actual_order_count",
    ):
        if key in deltas and int(deltas.get(key) or 0) != 0:
            raise DryRunEvidenceError(
                "dry_run_delta_nonzero",
                f"Dry Run delta {key} != 0",
            )
    counters = dry.get("counters") or {}
    for key in ("broker_submit", "db_order_insert", "create_order"):
        if key in counters and int(counters.get(key) or 0) != 0:
            raise DryRunEvidenceError(
                "dry_run_counter_nonzero",
                f"Dry Run counter {key} != 0",
            )

    checked_at = report.get("checked_at") or dry.get("checked_at")
    if not checked_at:
        raise DryRunEvidenceError(
            "dry_run_timestamp_missing",
            "Dry Run report timestamp missing",
        )
    ts = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ref = now or datetime.now(timezone.utc)
    age_h = (ref - ts).total_seconds() / 3600.0
    if age_h < 0:
        raise DryRunEvidenceError(
            "dry_run_timestamp_future",
            "Dry Run timestamp is in the future",
        )
    if age_h > float(max_age_hours):
        raise DryRunEvidenceError(
            "dry_run_stale",
            f"Dry Run evidence too old: {age_h:.1f}h > {max_age_hours}h",
        )

    correlation_id = report.get("correlation_id") or dry.get(
        "correlation_id"
    )
    digest = report_content_hash(report)
    return {
        "ok": True,
        "verdict": verdict,
        "uba_id": uba,
        "market": market,
        "requested_amount": str(amount_raw),
        "checked_at": ts.isoformat(),
        "age_hours": round(age_h, 3),
        "correlation_id": correlation_id,
        "report_hash": digest,
        "broker_submit": int(
            (deltas.get("broker_submit") if deltas else None)
            or (counters.get("broker_submit") if counters else None)
            or mutations.get("create_order")
            or 0
        ),
        "db_order_insert": int(
            (deltas.get("db_order_insert") if deltas else None)
            or (counters.get("db_order_insert") if counters else None)
            or 0
        ),
    }


def load_and_validate_dry_run_report(
    path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise DryRunEvidenceError(
            "dry_run_missing", f"Dry Run report not found: {p}"
        )
    raw = p.read_text(encoding="utf-8")
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DryRunEvidenceError(
            "dry_run_invalid_json", str(exc)
        ) from exc
    evidence = validate_step9_2_dry_run_evidence(report, **kwargs)
    evidence["path"] = str(p)
    return evidence


def Decimal_like(value: Any) -> int:
    """금액 문자열/숫자를 정수 KRW로 비교."""
    if value is None:
        raise ValueError("amount is None")
    text = str(value).strip()
    if "." in text:
        text = text.split(".", 1)[0]
    return int(text)
