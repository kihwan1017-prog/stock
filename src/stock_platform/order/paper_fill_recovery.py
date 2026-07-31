"""Paper ACCEPTED TradingOrder 고착 복구 — Outbox auto-fill 재시도."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderStatus
from stock_platform.order.paper_outbox_fill_service import (
    PaperOutboxFillService,
)


def recover_stalled_paper_accepted_orders(
    session: Session,
    *,
    limit: int = 50,
    actor: str = "PAPER_FILL_RECOVERY",
) -> dict[str, Any]:
    """ACCEPTED + UBA NULL Paper 주문을 auto-fill 재시도."""

    rows = session.scalars(
        select(TradingOrderEntity)
        .where(
            TradingOrderEntity.status_code == OrderStatus.ACCEPTED.value,
            TradingOrderEntity.user_broker_account_id.is_(None),
        )
        .order_by(TradingOrderEntity.order_id.asc())
        .limit(int(limit))
    ).all()

    filled = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    svc = PaperOutboxFillService(session)

    for order in rows:
        meta = dict(order.metadata_payload or {})
        env = str(meta.get("environment") or "PAPER").upper()
        if env == "LIVE":
            skipped += 1
            continue
        result = svc.fill_accepted_order(
            int(order.order_id),
            actor=actor,
            environment_hint=env,
        )
        if result.filled:
            filled += 1
        else:
            skipped += 1
            if result.reason_code not in {
                "ALREADY_TERMINAL",
                "LIVE_ENVIRONMENT_BLOCKED",
                "USER_BROKER_ACCOUNT_BLOCKED",
            }:
                errors.append(
                    {
                        "order_id": order.order_id,
                        "reason": result.reason_code,
                    }
                )

    if filled:
        session.commit()

    return {
        "scanned": len(rows),
        "filled": filled,
        "skipped": skipped,
        "errors": errors[:20],
    }
