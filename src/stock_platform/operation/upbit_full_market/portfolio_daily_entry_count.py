"""Portfolio 일일 REAL entry 집계 — KST calendar day + AUTO BUY SoT.

정책명 portfolio_daily_entry_limit 의 canonical 의미 (2026-08-27):
  당일(KST) REAL AUTO BUY 중 **quota 소비** 건수.

소비(comsumed) 정의:
  - filled_quantity > 0 (FILLED / PARTIAL / cancel-after-partial 포함)
  - 또는 아직 terminal이 아닌 open reservation (ACCEPTED 등)

미소비 (quota 미차감):
  - CANCELLED/FAILED 등 terminal + filled_quantity = 0
  - 미전송 retire (UNSUBMITTED_LIVE_RETIRED)
  - MANUAL / SHADOW / PAPER / SELL

동일 order_id의 multiple fills → 1회.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.orm import Session

from stock_platform.order.daily_risk_order_count import (
    day_start_kst_as_utc,
    retired_unsubmitted_exclusion_clause,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderStatus

# admission / blocking 과 동일한 open reservation
_OPEN_RESERVATION_STATUSES = frozenset(
    {
        OrderStatus.CREATED.value,
        OrderStatus.PENDING.value,
        OrderStatus.SUBMITTING.value,
        OrderStatus.SENT.value,
        OrderStatus.ACCEPTED.value,
        OrderStatus.PARTIALLY_FILLED.value,
        OrderStatus.REMOTE_LOOKUP_PENDING.value,
        OrderStatus.CANCEL_REQUESTED.value,
        OrderStatus.REPLACE_REQUESTED.value,
    }
)

_TERMINAL_ZERO_FILL_STATUSES = frozenset(
    {
        OrderStatus.CANCELLED.value,
        OrderStatus.FAILED.value,
        OrderStatus.REJECTED.value,
    }
)


def _auto_live_buy_base_filters(
    uba_id: int,
    day_start: datetime,
):
    auto_meta = TradingOrderEntity.metadata_payload["order_source"].astext
    return and_(
        TradingOrderEntity.user_broker_account_id == int(uba_id),
        TradingOrderEntity.created_at >= day_start,
        TradingOrderEntity.side_code == "BUY",
        TradingOrderEntity.broker_code == "UPBIT",
        auto_meta == "AUTO",
        not_(retired_unsubmitted_exclusion_clause()),
        or_(
            TradingOrderEntity.execution_mode.is_(None),
            TradingOrderEntity.execution_mode == "LIVE",
        ),
    )


def _consumed_or_reserved_clause():
    """Quota 소비: 체결 노출 또는 아직 open reservation."""

    filled_positive = func.coalesce(TradingOrderEntity.filled_quantity, 0) > 0
    open_reservation = TradingOrderEntity.status_code.in_(
        list(_OPEN_RESERVATION_STATUSES)
    )
    return or_(filled_positive, open_reservation)


def count_portfolio_daily_real_entries(
    session: Session,
    user_broker_account_id: int,
    *,
    now: datetime | None = None,
) -> int:
    """오늘(KST) portfolio 일일 한도에 사용하는 REAL AUTO BUY quota 건수."""

    uba_id = int(user_broker_account_id)
    day_start = day_start_kst_as_utc(now)
    count = session.scalar(
        select(func.count())
        .select_from(TradingOrderEntity)
        .where(
            _auto_live_buy_base_filters(uba_id, day_start),
            _consumed_or_reserved_clause(),
        )
    )
    return int(count or 0)


def count_portfolio_daily_consumed_entries(
    session: Session,
    user_broker_account_id: int,
    *,
    now: datetime | None = None,
) -> int:
    """체결 노출(filled_quantity>0)만 — 표시용 consumed."""

    uba_id = int(user_broker_account_id)
    day_start = day_start_kst_as_utc(now)
    count = session.scalar(
        select(func.count())
        .select_from(TradingOrderEntity)
        .where(
            _auto_live_buy_base_filters(uba_id, day_start),
            func.coalesce(TradingOrderEntity.filled_quantity, 0) > 0,
        )
    )
    return int(count or 0)


def count_portfolio_daily_reserved_entries(
    session: Session,
    user_broker_account_id: int,
    *,
    now: datetime | None = None,
) -> int:
    """아직 open인 AUTO BUY reservation (미체결 대기)."""

    uba_id = int(user_broker_account_id)
    day_start = day_start_kst_as_utc(now)
    count = session.scalar(
        select(func.count())
        .select_from(TradingOrderEntity)
        .where(
            _auto_live_buy_base_filters(uba_id, day_start),
            TradingOrderEntity.status_code.in_(list(_OPEN_RESERVATION_STATUSES)),
            func.coalesce(TradingOrderEntity.filled_quantity, 0) <= 0,
        )
    )
    return int(count or 0)


def count_portfolio_daily_zero_fill_cancelled(
    session: Session,
    user_broker_account_id: int,
    *,
    now: datetime | None = None,
) -> int:
    """0-fill terminal cancel — quota 미소비 (표시용)."""

    uba_id = int(user_broker_account_id)
    day_start = day_start_kst_as_utc(now)
    count = session.scalar(
        select(func.count())
        .select_from(TradingOrderEntity)
        .where(
            _auto_live_buy_base_filters(uba_id, day_start),
            TradingOrderEntity.status_code.in_(
                list(_TERMINAL_ZERO_FILL_STATUSES)
            ),
            func.coalesce(TradingOrderEntity.filled_quantity, 0) <= 0,
        )
    )
    return int(count or 0)


def summarize_portfolio_daily_entries(
    session: Session,
    user_broker_account_id: int,
    *,
    daily_limit: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """운영 표시용 — 오늘 진입 / 한도 / 잔여 / breakdown (KST)."""

    uba_id = int(user_broker_account_id)
    limit = max(1, int(daily_limit))
    now_utc = now or datetime.now(timezone.utc)
    day_start = day_start_kst_as_utc(now_utc)
    used = count_portfolio_daily_real_entries(session, uba_id, now=now_utc)
    consumed = count_portfolio_daily_consumed_entries(
        session, uba_id, now=now_utc
    )
    reserved = count_portfolio_daily_reserved_entries(
        session, uba_id, now=now_utc
    )
    zero_fill_cancelled = count_portfolio_daily_zero_fill_cancelled(
        session, uba_id, now=now_utc
    )
    remaining = max(0, limit - used)
    return {
        "user_broker_account_id": uba_id,
        "timezone": "Asia/Seoul",
        "day_start_utc": day_start.isoformat(),
        "entry_count": used,
        "entry_limit": limit,
        "remaining": remaining,
        "blocking": used >= limit,
        "consumed_count": consumed,
        "reserved_count": reserved,
        "zero_fill_cancelled_count": zero_fill_cancelled,
        "count_source": "REAL_AUTO_BUY_CONSUMED_OR_RESERVED",
        "canonical_meaning_ko": (
            "실제 신규 포지션 진입(체결) + 미체결 open reservation. "
            "0-fill 취소는 quota 미소비."
        ),
        "excludes": [
            "SUPERSEDED_SELECTION",
            "SELECTED_WITHOUT_BUY",
            "SLOT_REPLACEMENT",
            "SELL",
            "SHADOW",
            "PAPER",
            "MANUAL",
            "RETIRED_UNSUBMITTED",
            "ZERO_FILL_CANCELLED",
        ],
        "label_ko": (
            f"오늘 진입 {consumed} / {limit} "
            f"(대기 {reserved}, 취소·미체결 {zero_fill_cancelled})"
        ),
    }


def order_counts_toward_daily_quota(order: TradingOrderEntity) -> bool:
    """단건 order가 현재 count query에 포함되는지 (감사/테스트용)."""

    meta = order.metadata_payload if isinstance(
        order.metadata_payload, dict
    ) else {}
    if str(order.side_code or "").upper() != "BUY":
        return False
    if str(order.broker_code or "").upper() != "UPBIT":
        return False
    if str(meta.get("order_source") or "").upper() != "AUTO":
        return False
    env = str(meta.get("environment") or order.execution_mode or "LIVE").upper()
    if env not in {"LIVE", ""} and order.execution_mode not in (None, "LIVE"):
        return False
    filled = Decimal(str(order.filled_quantity or 0))
    status = str(order.status_code or "")
    if filled > 0:
        return True
    if status in _OPEN_RESERVATION_STATUSES:
        return True
    return False
