from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.execution_models import (
    KiwoomExecutionEvent,
)
from stock_platform.trading.execution_entities import (
    TradingExecution,
)


class TradingExecutionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def exists(
        self,
        *,
        broker_code: str,
        broker_execution_id: str,
    ) -> bool:
        stmt = select(
            TradingExecution.execution_id
        ).where(
            TradingExecution.broker_code
            == broker_code,
            TradingExecution.broker_execution_id
            == broker_execution_id,
        )
        return (
            self._session.scalar(stmt)
            is not None
        )

    def create(
        self,
        *,
        order_id: int,
        event: KiwoomExecutionEvent,
        broker_code: str = "KIWOOM",
    ) -> TradingExecution:
        entity = TradingExecution(
            order_id=order_id,
            broker_code=broker_code,
            broker_order_id=(
                event.broker_order_id
            ),
            broker_execution_id=(
                event.broker_execution_id
            ),
            symbol=event.symbol,
            side_code=event.side_code,
            execution_price=(
                event.execution_price
            ),
            execution_quantity=(
                event.execution_quantity
            ),
            executed_at=event.executed_at,
            raw_json=event.raw_payload,
        )
        self._session.add(entity)
        self._session.flush()
        return entity

    def list_by_order_id(
        self,
        order_id: int,
    ) -> list[TradingExecution]:
        stmt = (
            select(TradingExecution)
            .where(
                TradingExecution.order_id
                == order_id
            )
            .order_by(
                TradingExecution.executed_at
            )
        )
        return list(
            self._session.scalars(stmt)
        )
