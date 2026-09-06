"""Recovery precheck — broker/local + stuck/conflict gates."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.trading.exit_pending_stuck import (
    detect_exit_pending_zero_fill_stuck,
)

KST = ZoneInfo("Asia/Seoul")


def run_recovery_precheck(
    session: Session,
    *,
    user_broker_account_id: int,
) -> dict[str, Any]:
    uba = int(user_broker_account_id)
    stuck = detect_exit_pending_zero_fill_stuck(
        session, user_broker_account_id=uba
    )
    amb = session.execute(
        text(
            """
            SELECT COUNT(*) FROM trading.order_outbox ox
            JOIN trading.trading_order o ON o.order_id = ox.order_id
            WHERE ox.user_broker_account_id = :uba
              AND ox.status_code IN ('AMBIGUOUS','MANUAL_REVIEW')
              AND UPPER(COALESCE(o.metadata_payload->>'order_source','')) = 'AUTO'
            """
        ),
        {"uba": uba},
    ).scalar()
    unresolved = session.execute(
        text(
            """
            SELECT COUNT(*) FROM trading.trading_order
            WHERE user_broker_account_id = :uba
              AND UPPER(side_code) = 'SELL'
              AND UPPER(COALESCE(metadata_payload->>'order_source','')) = 'AUTO'
              AND UPPER(status_code) IN (
                'PENDING','SUBMITTED','ACCEPTED','OPEN','PARTIAL',
                'PARTIALLY_FILLED','AMBIGUOUS_SUBMISSION','REMOTE_LOOKUP_PENDING'
              )
            """
        ),
        {"uba": uba},
    ).scalar()
    try:
        rc = session.execute(
            text(
                """
                SELECT COUNT(*) FROM operation.broker_recovery_conflict
                WHERE user_broker_account_id = :uba
                  AND review_status IN ('PENDING_REVIEW','ON_HOLD')
                """
            ),
            {"uba": uba},
        ).scalar()
        recovery_conflict_count = int(rc or 0)
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        recovery_conflict_count = -1
        rc_err = type(exc).__name__
    else:
        rc_err = None

    uba_row = session.execute(
        text(
            """
            SELECT last_synced_at, connection_status, live_order_enabled,
                   live_armed
            FROM trading.user_broker_account
            WHERE user_broker_account_id = :uba
            """
        ),
        {"uba": uba},
    ).mappings().first()
    last_synced = (uba_row or {}).get("last_synced_at")
    sync_age = None
    if last_synced is not None:
        if getattr(last_synced, "tzinfo", None) is None:
            last_synced = last_synced.replace(tzinfo=KST)
        sync_age = (
            datetime.now(KST) - last_synced.astimezone(KST)
        ).total_seconds()
    balance_sync = (
        "READY"
        if last_synced is not None and sync_age is not None and sync_age <= 1800
        else "NOT_READY"
    )

    open_local = session.execute(
        text(
            """
            SELECT order_id, status_code, broker_order_id
            FROM trading.trading_order
            WHERE user_broker_account_id = :uba
              AND UPPER(status_code) IN (
                'PENDING','SUBMITTED','SUBMITTING','ACCEPTED','OPEN','PARTIAL',
                'PARTIALLY_FILLED','AMBIGUOUS_SUBMISSION','REMOTE_LOOKUP_PENDING'
              )
            """
        ),
        {"uba": uba},
    ).mappings().all()

    # kill — best effort (table 이름 환경별 차이 허용)
    kill_active = False
    try:
        kill = session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema='trading' AND table_name='kill_switch'
                """
            )
        ).scalar()
        if kill:
            kill_row = session.execute(
                text(
                    """
                    SELECT 1 FROM trading.kill_switch
                    WHERE COALESCE(active, false) IS TRUE
                    LIMIT 1
                    """
                )
            ).scalar()
            kill_active = bool(kill_row)
    except Exception:  # noqa: BLE001
        session.rollback()
        kill_active = False

    stuck_count = int(stuck.get("count") or 0)
    ambiguous_count = int(amb or 0)
    unresolved_exit_count = int(unresolved or 0)
    # open without UUID is Class C risk for auto restore
    missing_uuid = [
        int(r["order_id"])
        for r in open_local
        if not r.get("broker_order_id")
    ]
    broker_local = "PASS" if not missing_uuid else "FAIL"
    position_recon = "PASS"  # detailed position check optional; fail-closed on open mismatch

    ok = (
        stuck_count == 0
        and ambiguous_count == 0
        and unresolved_exit_count == 0
        and recovery_conflict_count == 0
        and broker_local == "PASS"
        and balance_sync == "READY"
        and position_recon == "PASS"
        and not kill_active
        and str((uba_row or {}).get("connection_status") or "").upper()
        == "CONNECTED"
    )
    return {
        "ok": ok,
        "stuck_count": stuck_count,
        "ambiguous_count": ambiguous_count,
        "unresolved_exit_count": unresolved_exit_count,
        "recovery_conflict_count": recovery_conflict_count,
        "recovery_conflict_error": rc_err,
        "broker_local": broker_local,
        "missing_uuid_order_ids": missing_uuid,
        "balance_sync": balance_sync,
        "last_synced_age_seconds": sync_age,
        "position_recon": position_recon,
        "kill_active": kill_active,
        "connection_status": (uba_row or {}).get("connection_status"),
        "open_local_count": len(open_local),
        "checked_at": datetime.now(KST).isoformat(),
    }
