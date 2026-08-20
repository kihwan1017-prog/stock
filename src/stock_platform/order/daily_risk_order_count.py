"""Risk daily_order_limit 집계 — 미전송 내부 폐기 주문 제외.

LiveOrderSafetyPipeline 등 LIVE Risk 게이트 전용.
PAPER/전체 주문 통계와 의미를 섞지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.orm import Session

from stock_platform.order.entities import (
    TradingOrderEntity,
    TradingOrderStatusHistoryEntity,
)
from stock_platform.order.models import OrderStatus
from stock_platform.order.unsubmitted_live_order_retire_service import (
    REASON_CODE as UNSUBMITTED_LIVE_RETIRED,
)

KST = ZoneInfo("Asia/Seoul")

# 상태 history에 남는 공식 retire reason
RETIRED_UNSUBMITTED_REASON = UNSUBMITTED_LIVE_RETIRED  # UNSUBMITTED_LIVE_RETIRED


def day_start_kst_as_utc(now: datetime | None = None) -> datetime:
    """Asia/Seoul 당일 00:00 → UTC."""

    now_kst = (now or datetime.now(timezone.utc)).astimezone(KST)
    return datetime(
        now_kst.year, now_kst.month, now_kst.day, tzinfo=KST
    ).astimezone(timezone.utc)


def is_retired_unsubmitted_for_daily_risk(
    *,
    status_code: str | None,
    broker_order_id: str | None,
    submission_attempt_count: int | None,
    has_unsubmitted_retire_history: bool,
) -> bool:
    """일일 Risk 건수에서 제외할 '공식 미전송 내부 폐기' 여부.

    CANCELLED 전부 제외가 아니다.
    실제 제출 후 CANCELLED(broker_order_id 또는 attempt>0)는 False.
    """

    if str(status_code or "") != OrderStatus.CANCELLED.value:
        return False
    if broker_order_id not in (None, ""):
        return False
    if int(submission_attempt_count or 0) != 0:
        return False
    return bool(has_unsubmitted_retire_history)


def _retired_unsubmitted_exists_clause():
    """status history에 UNSUBMITTED_LIVE_RETIRED → CANCELLED 증거가 있는지."""

    return (
        select(TradingOrderStatusHistoryEntity.order_status_history_id)
        .where(
            TradingOrderStatusHistoryEntity.order_id
            == TradingOrderEntity.order_id,
            TradingOrderStatusHistoryEntity.reason_code
            == RETIRED_UNSUBMITTED_REASON,
            TradingOrderStatusHistoryEntity.current_status_code
            == OrderStatus.CANCELLED.value,
        )
        .exists()
    )


def retired_unsubmitted_exclusion_clause():
    """daily_order_limit COUNT에서 빼는 SQL 조건 (NOT 이 조항)."""

    return and_(
        TradingOrderEntity.status_code == OrderStatus.CANCELLED.value,
        or_(
            TradingOrderEntity.broker_order_id.is_(None),
            TradingOrderEntity.broker_order_id == "",
        ),
        func.coalesce(TradingOrderEntity.submission_attempt_count, 0) == 0,
        _retired_unsubmitted_exists_clause(),
    )


def count_daily_risk_orders(
    session: Session,
    user_broker_account_id: int,
    *,
    now: datetime | None = None,
) -> int:
    """UBA별 오늘(KST) Risk daily_order_limit 사용 건수.

    포함: PENDING/QUEUED/SENT/제출 후 CANCELLED 등 일반 주문.
    제외: 공식 미전송 retire(UNSUBMITTED_LIVE_RETIRED) CANCELLED.

    참고:
    - LiveOrderSafetyPipeline은 verified EXIT에 대해 이 한도를 적용하지 않는다
      (protective EXIT가 ENTRY quota에 막히지 않음).
    - ENTRY-only 집계는 count_daily_entry_orders.
    """

    uba_id = int(user_broker_account_id)
    day_start = day_start_kst_as_utc(now)
    count = session.scalar(
        select(func.count())
        .select_from(TradingOrderEntity)
        .where(
            TradingOrderEntity.user_broker_account_id == uba_id,
            TradingOrderEntity.created_at >= day_start,
            not_(retired_unsubmitted_exclusion_clause()),
        )
    )
    return int(count or 0)


def count_daily_entry_orders(
    session: Session,
    user_broker_account_id: int,
    *,
    now: datetime | None = None,
) -> int:
    """오늘(KST) BUY(ENTRY) 건수만 — EXIT는 제외."""

    uba_id = int(user_broker_account_id)
    day_start = day_start_kst_as_utc(now)
    count = session.scalar(
        select(func.count())
        .select_from(TradingOrderEntity)
        .where(
            TradingOrderEntity.user_broker_account_id == uba_id,
            TradingOrderEntity.created_at >= day_start,
            TradingOrderEntity.side_code == "BUY",
            not_(retired_unsubmitted_exclusion_clause()),
        )
    )
    return int(count or 0)


def summarize_daily_risk_orders(
    session: Session,
    user_broker_account_id: int,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """진단용 — 생성 건수 / retire 제외 / Risk 집계."""

    uba_id = int(user_broker_account_id)
    day_start = day_start_kst_as_utc(now)
    total = int(
        session.scalar(
            select(func.count())
            .select_from(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id == uba_id,
                TradingOrderEntity.created_at >= day_start,
            )
        )
        or 0
    )
    retired = int(
        session.scalar(
            select(func.count())
            .select_from(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id == uba_id,
                TradingOrderEntity.created_at >= day_start,
                retired_unsubmitted_exclusion_clause(),
            )
        )
        or 0
    )
    risk_counted = count_daily_risk_orders(
        session, uba_id, now=now
    )
    return {
        "user_broker_account_id": uba_id,
        "day_start_utc": day_start.isoformat(),
        "total_created_today": total,
        "retired_unsubmitted": retired,
        "risk_counted_orders": risk_counted,
    }
