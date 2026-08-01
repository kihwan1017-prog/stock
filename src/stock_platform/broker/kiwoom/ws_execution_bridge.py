"""Kiwoom Order WS 이벤트 → TradingOrder ExecutionSync 브리지."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from stock_platform.broker.kiwoom.execution_models import (
    KiwoomExecutionEvent,
)
from stock_platform.broker.kiwoom.ws_models import (
    KiwoomOrderEventType,
    KiwoomOrderExecutionEvent,
)


def order_execution_event_to_kiwoom_execution(
    event: KiwoomOrderExecutionEvent,
    *,
    previous_filled_quantity: Decimal | None = None,
) -> KiwoomExecutionEvent | None:
    """
    Pending 스냅샷용 WS 이벤트를 TradingOrder sync 이벤트로 변환.

    FILLED / PARTIALLY_FILLED 만 변환한다. 증분 수량은
    previous_filled_quantity가 있으면 (현재 filled - previous)를 사용하고,
    없으면 filled_quantity 전체를 한 번에 반영한다(재시작/첫 이벤트).
    """

    if event.event_type not in {
        KiwoomOrderEventType.FILLED,
        KiwoomOrderEventType.PARTIALLY_FILLED,
    }:
        return None

    fill_price = event.fill_price or event.average_fill_price
    if fill_price is None or Decimal(str(fill_price)) <= 0:
        return None

    filled = Decimal(str(event.filled_quantity or 0))
    if previous_filled_quantity is not None:
        delta = filled - Decimal(str(previous_filled_quantity))
    else:
        delta = filled

    if delta <= 0:
        return None

    # broker_execution_id: WS에 고유 체결 ID가 없으면 합성 (idempotent 키)
    raw: dict[str, Any] = dict(event.raw_data or {})
    broker_execution_id = str(
        raw.get("broker_execution_id")
        or raw.get("execution_id")
        or raw.get("exec_id")
        or f"{event.broker_order_id}:{filled}:{fill_price}"
    )

    executed_at = event.event_time or event.received_at or datetime.now(
        timezone.utc
    )

    return KiwoomExecutionEvent(
        broker_order_id=str(event.broker_order_id),
        broker_execution_id=broker_execution_id,
        symbol=str(event.symbol),
        side_code=str(event.side) if event.side else None,
        execution_price=Decimal(str(fill_price)),
        execution_quantity=delta,
        remaining_quantity=Decimal(str(event.remaining_quantity or 0)),
        executed_at=executed_at,
        raw_payload=raw,
    )
