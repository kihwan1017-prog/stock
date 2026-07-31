"""Paper ACCEPTED TradingOrder 고착 복구 — Outbox auto-fill 재시도."""

from __future__ import annotations

from datetime import datetime, timezone
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
    """ACCEPTED + UBA NULL Paper 주문을 auto-fill 재시도.

    - 최신 주문 우선 (공유 DB starvation 완화)
    - SKIP LOCKED 로 경합 대기 없이 통과
    - 주문 단위 try/except (PaperOrderRepository.save가 commit 하므로 nested 미사용)
    """

    rows = list(
        session.scalars(
            select(TradingOrderEntity)
            .where(
                TradingOrderEntity.status_code
                == OrderStatus.ACCEPTED.value,
                TradingOrderEntity.user_broker_account_id.is_(None),
            )
            .order_by(TradingOrderEntity.order_id.desc())
            .limit(int(limit))
            .with_for_update(skip_locked=True)
        ).all()
    )
    # ID만 확보 후 락 해제 — fill 경로의 내부 commit과 충돌 방지
    order_ids = [int(r.order_id) for r in rows]
    session.commit()

    filled = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for order_id in order_ids:
        try:
            svc = PaperOutboxFillService(session)
            order = session.get(TradingOrderEntity, order_id)
            if order is None:
                skipped += 1
                continue
            meta = dict(order.metadata_payload or {})
            env = str(meta.get("environment") or "PAPER").upper()
            if env == "LIVE":
                skipped += 1
                continue

            result = svc.fill_accepted_order(
                order_id,
                actor=actor,
                environment_hint=env,
            )
            if result.filled:
                filled += 1
                session.commit()
            else:
                skipped += 1
                order = session.get(TradingOrderEntity, order_id)
                if order is not None:
                    meta = dict(order.metadata_payload or {})
                    meta["paper_auto_fill_last_error"] = result.reason_code
                    meta["paper_auto_fill_last_attempt_at"] = now
                    order.metadata_payload = meta
                    session.commit()
                if result.reason_code not in {
                    "ALREADY_TERMINAL",
                    "LIVE_ENVIRONMENT_BLOCKED",
                    "USER_BROKER_ACCOUNT_BLOCKED",
                    "IDEMPOTENT_REPLAY",
                    "NO_POSITION_CANCELLED",
                }:
                    errors.append(
                        {
                            "order_id": order_id,
                            "reason": result.reason_code,
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            skipped += 1
            try:
                order = session.get(TradingOrderEntity, order_id)
                if order is not None:
                    meta = dict(order.metadata_payload or {})
                    meta["paper_auto_fill_last_error"] = type(exc).__name__
                    meta["paper_auto_fill_last_attempt_at"] = now
                    order.metadata_payload = meta
                    session.commit()
            except Exception:  # noqa: BLE001
                session.rollback()
            errors.append(
                {
                    "order_id": order_id,
                    "reason": type(exc).__name__,
                }
            )

    return {
        "scanned": len(order_ids),
        "filled": filled,
        "skipped": skipped,
        "errors": errors[:20],
    }
