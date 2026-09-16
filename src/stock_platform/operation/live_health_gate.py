"""STEP 8-5-20 — LIVE 주문 Health CRITICAL Fail Closed."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session


class LiveHealthBlockedError(PermissionError):
    """시스템 Health CRITICAL — LIVE 신규 주문 차단."""


def evaluate_live_order_health(session: Session) -> dict:
    """LIVE 주문 허용 여부를 경량 검사한다 (전체 Health 빌드 없이)."""

    from stock_platform.broker.account_models import BrokerAccountSnapshotEntity
    from stock_platform.broker.snapshot_constants import BrokerSnapshotStatus
    from stock_platform.risk_engine.daily_loss_entities import (
        AccountDailyLossEntity,
    )

    active_missing_uba = int(
        session.scalar(
            select(func.count())
            .select_from(BrokerAccountSnapshotEntity)
            .where(
                BrokerAccountSnapshotEntity.snapshot_status
                == BrokerSnapshotStatus.ACTIVE.value,
                BrokerAccountSnapshotEntity.user_broker_account_id.is_(None),
                BrokerAccountSnapshotEntity.paper_account_id.is_(None),
            )
        )
        or 0
    )
    daily_loss_missing = int(
        session.scalar(
            select(func.count())
            .select_from(AccountDailyLossEntity)
            .where(
                AccountDailyLossEntity.user_broker_account_id.is_(None),
                AccountDailyLossEntity.paper_account_id.is_(None),
            )
        )
        or 0
    )

    critical = active_missing_uba > 0 or daily_loss_missing > 0
    return {
        "status": "CRITICAL" if critical else "HEALTHY",
        "uba_missing_active_snapshot_count": active_missing_uba,
        "daily_loss_missing_scope_count": daily_loss_missing,
        "live_orders_allowed": not critical,
    }


def assert_live_orders_allowed(session: Session) -> None:
    """LIVE 신규 주문 전 호출 — CRITICAL 이면 Fail Closed."""

    result = evaluate_live_order_health(session)
    if not result["live_orders_allowed"]:
        raise LiveHealthBlockedError(
            "LIVE orders blocked: system health CRITICAL "
            f"(uba_missing={result['uba_missing_active_snapshot_count']}, "
            f"daily_loss_missing={result['daily_loss_missing_scope_count']})"
        )
