"""Order Outbox 스케줄러 싱글톤 — PAPER 어댑터 기본."""

from __future__ import annotations

from stock_platform.broker.paper.adapter import PaperBrokerAdapter
from stock_platform.database.session import get_session_factory
from stock_platform.order.outbox_dispatcher import (
    OrderOutboxDispatcher,
)
from stock_platform.order.outbox_scheduler import (
    OrderOutboxScheduler,
)
from stock_platform.order.outbox_worker import (
    OrderOutboxWorker,
)


def build_order_outbox_scheduler() -> OrderOutboxScheduler:
    # 기본은 Paper. 실거래는 KIWOOM_LIVE + transition 가드 경로에서만.
    return OrderOutboxScheduler(
        worker=OrderOutboxWorker(
            session_factory=get_session_factory(),
            dispatcher=OrderOutboxDispatcher(
                PaperBrokerAdapter()
            ),
            worker_id="api-outbox-1",
        ),
        interval_seconds=1.0,
    )


order_outbox_scheduler = build_order_outbox_scheduler()
