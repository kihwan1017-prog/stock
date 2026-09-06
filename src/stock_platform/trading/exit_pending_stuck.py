"""EXIT_PENDING + ACCEPTED/SUBMITTED SELL zero-fill stuck 감지 (READ).

강제 SELL/cancel 없음. Watchdog는 fill-sync + lifecycle reconcile만 수행.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# 기본 stuck age — SoT: upbit_portfolio_entry_pending_timeout_seconds (canonical)
DEFAULT_STUCK_AGE_SECONDS = 120


def _canonical_stuck_age_seconds() -> int:
    try:
        from stock_platform.common.settings import get_settings

        settings = get_settings()
        return int(
            float(
                getattr(
                    settings,
                    "upbit_portfolio_entry_pending_timeout_seconds",
                    DEFAULT_STUCK_AGE_SECONDS,
                )
                or DEFAULT_STUCK_AGE_SECONDS
            )
        )
    except Exception:  # noqa: BLE001
        return int(DEFAULT_STUCK_AGE_SECONDS)


def detect_exit_pending_zero_fill_stuck(
    session: Session,
    *,
    user_broker_account_id: int,
    now: datetime | None = None,
    max_age_seconds: int | None = None,
) -> dict[str, Any]:
    """EXIT_PENDING 슬롯에 zero-fill open SELL이 max_age 초과면 stuck."""

    if max_age_seconds is None:
        max_age_seconds = _canonical_stuck_age_seconds()
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=int(max_age_seconds))
    rows = session.execute(
        text(
            """
            SELECT s.slot_id, s.symbol, s.status, s.updated_at,
                   o.order_id, o.status_code AS order_status,
                   o.broker_order_id,
                   o.filled_quantity, o.created_at AS order_created_at,
                   o.side_code,
                   o.order_type_code,
                   o.client_order_identifier,
                   ox.outbox_id, ox.status_code AS outbox_status,
                   ox.confirmation_status
            FROM operation.upbit_position_slot s
            JOIN trading.trading_order o
              ON o.user_broker_account_id = s.user_broker_account_id
             AND o.broker_code = 'UPBIT'
             AND o.symbol = s.symbol
             AND UPPER(o.side_code) = 'SELL'
             AND UPPER(o.status_code) IN (
                   'OPEN','PENDING','SUBMITTED','ACCEPTED','PARTIAL','NEW',
                   'AMBIGUOUS_SUBMISSION','REMOTE_LOOKUP_PENDING'
                 )
             AND COALESCE(o.filled_quantity, 0) = 0
            LEFT JOIN LATERAL (
                SELECT outbox_id, status_code, confirmation_status
                FROM trading.order_outbox
                WHERE order_id = o.order_id
                ORDER BY outbox_id DESC
                LIMIT 1
            ) ox ON TRUE
            WHERE s.user_broker_account_id = :uba
              AND s.status = 'EXIT_PENDING'
              AND o.created_at <= :cutoff
            ORDER BY o.created_at ASC
            """
        ),
        {
            "uba": int(user_broker_account_id),
            "cutoff": cutoff,
        },
    ).mappings().all()

    items = []
    for r in rows:
        created = r["order_created_at"]
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (now - created).total_seconds() if created else None
        items.append(
            {
                "slot_id": int(r["slot_id"]),
                "symbol": r["symbol"],
                "order_id": int(r["order_id"]),
                "order_status": r["order_status"],
                "order_type": r.get("order_type_code"),
                "broker_order_id": r.get("broker_order_id"),
                "client_order_identifier": r.get("client_order_identifier"),
                "outbox_id": (
                    int(r["outbox_id"]) if r.get("outbox_id") is not None else None
                ),
                "outbox_status": r.get("outbox_status"),
                "confirmation_status": r.get("confirmation_status"),
                "age_seconds": round(age, 1) if age is not None else None,
            }
        )
    return {
        "stuck": len(items) > 0,
        "count": len(items),
        "items": items,
        "max_age_seconds": int(max_age_seconds),
        "reason": "EXIT_PENDING_ZERO_FILL_STUCK" if items else None,
    }
