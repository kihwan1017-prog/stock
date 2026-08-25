"""Portfolio 일일 REAL entry 집계 — KST calendar day + AUTO BUY SoT.

정책명 portfolio_daily_entry_limit 의 canonical 의미:
  당일(KST) 신규 REAL AUTO BUY 주문 건수 (distinct order_id).

포함하지 않음:
  - SUPERSEDED / SELECTED 등 candidate selection / slot rotation
  - SELL / EXIT
  - SHADOW / PAPER
  - MANUAL
  - 미전송 retire(CANCELLED)
  - 동일 BUY의 다중 fill (order 1건 = entry 1회)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, not_, or_, select
from sqlalchemy.orm import Session

from stock_platform.order.daily_risk_order_count import (
    day_start_kst_as_utc,
    retired_unsubmitted_exclusion_clause,
)
from stock_platform.order.entities import TradingOrderEntity


def count_portfolio_daily_real_entries(
    session: Session,
    user_broker_account_id: int,
    *,
    now: datetime | None = None,
) -> int:
    """오늘(KST) portfolio 일일 한도에 사용하는 REAL AUTO BUY 건수."""

    uba_id = int(user_broker_account_id)
    day_start = day_start_kst_as_utc(now)
    auto_meta = TradingOrderEntity.metadata_payload["order_source"].astext
    count = session.scalar(
        select(func.count())
        .select_from(TradingOrderEntity)
        .where(
            TradingOrderEntity.user_broker_account_id == uba_id,
            TradingOrderEntity.created_at >= day_start,
            TradingOrderEntity.side_code == "BUY",
            TradingOrderEntity.broker_code == "UPBIT",
            auto_meta == "AUTO",
            not_(retired_unsubmitted_exclusion_clause()),
            # SHADOW / PAPER execution_mode 제외 (NULL= LIVE 관례 허용)
            or_(
                TradingOrderEntity.execution_mode.is_(None),
                TradingOrderEntity.execution_mode == "LIVE",
            ),
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
    """운영 표시용 — 오늘 진입 / 한도 / 잔여 (KST)."""

    uba_id = int(user_broker_account_id)
    limit = max(1, int(daily_limit))
    now_utc = now or datetime.now(timezone.utc)
    day_start = day_start_kst_as_utc(now_utc)
    used = count_portfolio_daily_real_entries(session, uba_id, now=now_utc)
    remaining = max(0, limit - used)
    return {
        "user_broker_account_id": uba_id,
        "timezone": "Asia/Seoul",
        "day_start_utc": day_start.isoformat(),
        "entry_count": used,
        "entry_limit": limit,
        "remaining": remaining,
        "blocking": used >= limit,
        "count_source": "REAL_AUTO_BUY_ORDER_DISTINCT",
        "excludes": [
            "SUPERSEDED_SELECTION",
            "SELECTED_WITHOUT_BUY",
            "SLOT_REPLACEMENT",
            "SELL",
            "SHADOW",
            "PAPER",
            "MANUAL",
            "RETIRED_UNSUBMITTED",
        ],
        "label_ko": "실제 자동매매 신규 진입 기준. 후보 교체/Shadow는 포함하지 않습니다.",
    }
