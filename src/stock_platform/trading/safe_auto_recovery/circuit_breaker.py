"""Recovery circuit breaker — settings-driven, no hardcode flood loops."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class CircuitPolicy:
    max_attempts: int = 3
    window_seconds: int = 3600
    cooldown_seconds: int = 1800


def load_circuit_policy(settings: Any | None = None) -> CircuitPolicy:
    if settings is None:
        from stock_platform.common.settings import get_settings

        settings = get_settings()
    return CircuitPolicy(
        max_attempts=int(
            getattr(settings, "safe_auto_recovery_circuit_max_attempts", 3)
        ),
        window_seconds=int(
            getattr(settings, "safe_auto_recovery_circuit_window_seconds", 3600)
        ),
        cooldown_seconds=int(
            getattr(
                settings, "safe_auto_recovery_circuit_cooldown_seconds", 1800
            )
        ),
    )


def evaluate_circuit(
    session: Session,
    *,
    user_broker_account_id: int,
    root_cause: str | None,
    policy: CircuitPolicy | None = None,
) -> dict[str, Any]:
    """동일 UBA(+root) 반복 복구 시도가 한도를 넘으면 OPEN."""

    pol = policy or load_circuit_policy()
    since = datetime.now(timezone.utc) - timedelta(seconds=pol.window_seconds)
    try:
        rows = session.execute(
            text(
                """
                SELECT recovery_id, root_cause, status, created_at
                FROM operation.autotrading_recovery_incident
                WHERE user_broker_account_id = :uba
                  AND created_at >= :since
                  AND status IN (
                    'RECOVER_ATTEMPTED','RECOVER_FAILED','RECOVER_SUCCESS',
                    'CIRCUIT_OPEN'
                  )
                ORDER BY created_at DESC
                LIMIT 50
                """
            ),
            {"uba": int(user_broker_account_id), "since": since},
        ).mappings().all()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        # 테이블 미적용 시 fail-closed: circuit unknown → treat as closed but note
        return {
            "open": False,
            "reason": "CIRCUIT_TABLE_UNAVAILABLE",
            "error": type(exc).__name__,
            "attempt_count": 0,
            "policy": pol.__dict__,
        }

    attempts = [dict(r) for r in rows]
    if root_cause:
        rc = str(root_cause).upper()
        matched = [
            a
            for a in attempts
            if str(a.get("root_cause") or "").upper() == rc
            or str(a.get("status") or "") == "CIRCUIT_OPEN"
        ]
    else:
        matched = attempts

    failed_or_try = [
        a
        for a in matched
        if str(a.get("status") or "")
        in {"RECOVER_ATTEMPTED", "RECOVER_FAILED", "CIRCUIT_OPEN"}
    ]
    open_ = len(failed_or_try) >= int(pol.max_attempts)
    return {
        "open": open_,
        "reason": "MAX_ATTEMPTS_IN_WINDOW" if open_ else "OK",
        "attempt_count": len(failed_or_try),
        "window_attempt_count": len(matched),
        "policy": pol.__dict__,
        "root_cause": root_cause,
    }
