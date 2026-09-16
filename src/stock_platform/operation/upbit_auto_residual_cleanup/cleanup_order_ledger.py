# -*- coding: utf-8 -*-
"""Persist controlled cleanup SELL as local FILLED trading_order (no broker call)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.order.entities import TradingOrderEntity


def persist_cleanup_sell_trading_order(
    session: Session,
    *,
    uba_id: int,
    symbol: str,
    executed_qty: Decimal,
    broker_order_uuid: str | None,
    identifier: str | None,
    binding_id: int,
    approval_id: str | None,
    paid_fee: Any = None,
    average_price: Decimal | None = None,
) -> TradingOrderEntity | None:
    """Cleanup FILLED 후 local SELL 기록 — post-fill order-net 정합용.

    이미 동일 broker_order_id가 있으면 noop.
    """

    qty = Decimal(str(executed_qty or 0))
    if qty <= 0:
        return None
    uuid = str(broker_order_uuid or "").strip()
    if uuid:
        existing = session.scalar(
            select(TradingOrderEntity).where(
                TradingOrderEntity.user_broker_account_id == int(uba_id),
                TradingOrderEntity.broker_order_id == uuid,
            )
        )
        if existing is not None:
            return existing

    now = datetime.now(timezone.utc)
    client_id = f"CRC-SELL-{binding_id}-{uuid4().hex[:12]}"
    row = TradingOrderEntity(
        client_order_id=client_id[:64],
        broker_order_id=uuid or None,
        broker_code="UPBIT",
        exchange_code="UPBIT",
        symbol=str(symbol).upper(),
        side_code="SELL",
        order_type_code="MARKET",
        time_in_force_code="IOC",
        order_quantity=qty,
        order_price=average_price,
        filled_quantity=qty,
        remaining_quantity=Decimal("0"),
        filled_amount=(average_price * qty) if average_price else Decimal("0"),
        average_fill_price=average_price,
        status_code="FILLED",
        user_broker_account_id=int(uba_id),
        client_order_identifier=(identifier or client_id)[:64],
        filled_at=now,
        accepted_at=now,
        first_filled_at=now,
        metadata_payload={
            "order_source": "CONTROLLED_AUTO_RESIDUAL_CLEANUP",
            "environment": "LIVE",
            "execution_mode": "LIVE",
            "binding_id": int(binding_id),
            "approval_id": approval_id,
            "path": "CONTROLLED_AUTO_RESIDUAL_CLEANUP",
            "upbit_paid_fee": str(paid_fee) if paid_fee is not None else None,
            "note": "local ledger for post-fill expected netting; broker already filled",
        },
    )
    session.add(row)
    session.flush()
    return row
