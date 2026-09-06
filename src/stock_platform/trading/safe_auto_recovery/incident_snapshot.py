"""Incident snapshot persistence — DB + .run JSON evidence."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_dir() -> Path:
    return Path(__file__).resolve().parents[4] / ".run"


def write_run_evidence(snapshot: dict[str, Any]) -> str:
    out = _run_dir() / (
        f"autotrading_incident_{snapshot.get('incident_id')}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    # redact tokens
    safe = json.loads(json.dumps(snapshot, default=str))
    def _redact(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: (
                    "<redacted>"
                    if "token" in str(k).lower() or "secret" in str(k).lower()
                    else _redact(v)
                )
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_redact(x) for x in obj]
        return obj

    safe = _redact(safe)
    out.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return str(out)


def build_incident_snapshot(
    *,
    user_broker_account_id: int,
    broker_code: str,
    primary_blocker: str | None,
    failure_event_type: str | None,
    first_zero: str | None,
    ops: dict[str, Any] | None,
    precheck: dict[str, Any] | None,
    classification: dict[str, Any] | None,
    recovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ops = ops or {}
    stack = ops.get("runtime_stack") or {}
    feed = ops.get("market_feed") or {}
    unatt = ops.get("unattended") or {}
    incident_id = f"inc-{user_broker_account_id}-{uuid.uuid4().hex[:12]}"
    op_auth = (
        unatt.get("operator_authorization")
        if isinstance(unatt, dict)
        else None
    )
    if not isinstance(op_auth, dict):
        op_auth = {}
    return {
        "incident_id": incident_id,
        "occurred_at": _now().isoformat(),
        "user_broker_account_id": int(user_broker_account_id),
        "broker_code": str(broker_code or "").upper(),
        "root_blocker": primary_blocker,
        "failure_event_type": failure_event_type,
        "funnel_first_zero": first_zero,
        "AUTO": ops.get("auto_trading_state"),
        "LIVE": ops.get("live"),
        "ARM": ops.get("arm"),
        "Activation": ops.get("activation"),
        "activation_id": ops.get("activation_id"),
        "activation_expires_at": ops.get("activation_expires_at"),
        "arm_expires_at": ops.get("arm_expires_at"),
        "unattended": unatt.get("status_code")
        if isinstance(unatt, dict)
        else unatt,
        # Operator Authorization (SoT = unattended lease)
        "authorization_id": op_auth.get("authorization_id")
        or (unatt.get("authorization_id") if isinstance(unatt, dict) else None),
        "authorization_status": op_auth.get("status")
        or (unatt.get("status_code") if isinstance(unatt, dict) else None),
        "authorization_expires_at": op_auth.get("valid_until")
        or (unatt.get("authorized_until") if isinstance(unatt, dict) else None),
        "renewal_status": op_auth.get("renewal_status"),
        "renewal_failure_reason": (
            (op_auth.get("last_horizon_auto_renew") or {}).get("reason")
            if isinstance(op_auth.get("last_horizon_auto_renew"), dict)
            else None
        ),
        "stack": stack,
        "backend_pid": os.getpid(),
        "feed_status": feed.get("status") if isinstance(feed, dict) else None,
        "feed_age_seconds": (feed.get("detail") or {}).get("age_seconds")
        if isinstance(feed, dict)
        else None,
        "precheck": precheck,
        "classification": classification,
        "recovery": recovery or {},
        "blockers": ops.get("blockers"),
        "warnings": ops.get("warnings"),
        "risk": ops.get("risk"),
        "ai_state": ops.get("ai_state"),
    }


def persist_incident(
    session: Session,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    evidence_path = write_run_evidence(snapshot)
    snapshot["evidence_path"] = evidence_path
    try:
        row = session.execute(
            text(
                """
                INSERT INTO operation.autotrading_recovery_incident (
                  incident_id, recovery_id, user_broker_account_id, broker_code,
                  root_cause, failure_event_type, recovery_class, status,
                  eligibility, snapshot_json, evidence_path, attempt_count,
                  created_at, updated_at
                ) VALUES (
                  :incident_id, :recovery_id, :uba, :broker,
                  :root_cause, :failure_event_type, :recovery_class, :status,
                  :eligibility, CAST(:snapshot_json AS jsonb), :evidence_path,
                  :attempt_count, :created_at, :updated_at
                )
                RETURNING id
                """
            ),
            {
                "incident_id": snapshot["incident_id"],
                "recovery_id": snapshot.get("recovery", {}).get("recovery_id")
                or snapshot["incident_id"],
                "uba": int(snapshot["user_broker_account_id"]),
                "broker": snapshot.get("broker_code") or "UPBIT",
                "root_cause": snapshot.get("root_blocker"),
                "failure_event_type": snapshot.get("failure_event_type"),
                "recovery_class": (snapshot.get("classification") or {}).get(
                    "recovery_class"
                ),
                "status": (snapshot.get("recovery") or {}).get("status")
                or "SNAPSHOT",
                "eligibility": (snapshot.get("classification") or {}).get(
                    "eligibility"
                ),
                "snapshot_json": json.dumps(snapshot, default=str),
                "evidence_path": evidence_path,
                "attempt_count": int(
                    (snapshot.get("recovery") or {}).get("attempt_count") or 0
                ),
                "created_at": _now(),
                "updated_at": _now(),
            },
        ).first()
        session.flush()
        snapshot["db_id"] = int(row[0]) if row else None
        snapshot["db_persisted"] = True
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        snapshot["db_persisted"] = False
        snapshot["db_error"] = type(exc).__name__
    return snapshot
