"""STEP 9-6 — 브로커 체결 결과를 DB order/execution에 반영."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from stock_platform.auth import models as _auth_models  # noqa: F401
from stock_platform.broker.credential_adapter_factory import (
    build_upbit_adapter_for_uba,
)
from stock_platform.database.session import get_session_factory
from stock_platform.order.models import OrderStatus
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.strategy_deployment import (  # noqa: F401
    definition_entities as _strategy_entities,
)
from stock_platform.trading.execution_entities import TradingExecution

ORDER_ID = 250
UUID = "00175133-d943-42fa-aa33-d432d81e3499"


def main() -> None:
    session = get_session_factory()()
    try:
        adapter = build_upbit_adapter_for_uba(session, 58)
        remote = adapter._client.get_order(uuid=UUID)
        trade = (remote.get("trades") or [{}])[0]
        filled = Decimal(str(remote.get("executed_volume") or 0))
        avg = Decimal(str(trade.get("price") or 0))
        funds = Decimal(str(trade.get("funds") or 0))
        fee = Decimal(str(remote.get("paid_fee") or 0))
        if filled <= 0:
            raise SystemExit("NO_FILL")

        repo = TradingOrderRepository(session)
        order = repo.get(ORDER_ID)
        if order is None:
            raise SystemExit("ORDER_MISSING")

        if order.status_code == OrderStatus.SUBMITTING.value:
            order = repo.change_status(
                entity=order,
                new_status=OrderStatus.ACCEPTED,
                actor="STEP9_6_RECONCILE",
                reason_code="BROKER_ACCEPTED",
                commit=False,
            )
        if order.status_code != OrderStatus.FILLED.value:
            order = repo.change_status(
                entity=order,
                new_status=OrderStatus.FILLED,
                actor="STEP9_6_RECONCILE",
                reason_code="UPBIT_MARKET_BUY_FILLED",
                message=(
                    "Upbit market buy state=cancel with executed_volume>0 "
                    "(KRW residual cancel after fill)"
                ),
                commit=False,
            )

        order.filled_quantity = filled
        order.remaining_quantity = Decimal("0")
        order.average_fill_price = avg
        order.broker_order_id = UUID
        order.filled_at = datetime.now(timezone.utc)
        if hasattr(order, "upbit_client_identifier"):
            order.upbit_client_identifier = remote.get("identifier")

        from sqlalchemy import select

        trade_uuid = str(trade.get("uuid") or f"{UUID}-fill")
        existing = session.scalar(
            select(TradingExecution).where(
                TradingExecution.broker_code == "UPBIT",
                TradingExecution.broker_execution_id == trade_uuid,
            )
        )
        if existing is None:
            session.add(
                TradingExecution(
                    order_id=ORDER_ID,
                    broker_code="UPBIT",
                    broker_order_id=UUID,
                    broker_execution_id=trade_uuid,
                    symbol="KRW-BTC",
                    side_code="BUY",
                    execution_price=avg,
                    execution_quantity=filled,
                    executed_at=datetime.now(timezone.utc),
                    raw_json={
                        "funds": str(funds),
                        "paid_fee": str(fee),
                        "source": "STEP9_6_RECONCILE",
                        "broker_state": remote.get("state"),
                    },
                )
            )
        session.commit()
        print(
            "synced",
            order.status_code,
            str(order.filled_quantity),
            str(order.average_fill_price),
            remote.get("identifier"),
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
