from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from stock_platform.order.entities import TradingOrderEntity, TradingOrderStatusHistoryEntity
from stock_platform.order.models import CreateOrderCommand, OrderStatus

class TradingOrderRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, command: CreateOrderCommand, client_order_id: str, actor: str = "SYSTEM"):
        entity = TradingOrderEntity(
            client_order_id=client_order_id,
            account_id=command.account_id,
            broker_code=command.broker_code.upper(),
            exchange_code=command.exchange_code.upper(),
            symbol=command.symbol.upper(),
            strategy_code=command.strategy_code,
            strategy_deployment_id=command.strategy_deployment_id,
            portfolio_id=command.portfolio_id,
            position_id=command.position_id,
            side_code=command.side.value,
            order_type_code=command.order_type.value,
            time_in_force_code=command.time_in_force.value,
            order_quantity=command.quantity,
            order_price=command.price,
            filled_quantity=Decimal("0"),
            remaining_quantity=command.quantity,
            filled_amount=Decimal("0"),
            status_code=OrderStatus.CREATED.value,
            metadata_payload=command.metadata_payload or {},
        )
        self.session.add(entity)
        self.session.flush()
        self.session.add(TradingOrderStatusHistoryEntity(
            order_id=entity.order_id,
            previous_status_code=None,
            current_status_code=OrderStatus.CREATED.value,
            reason_code="ORDER_CREATED",
            message="Order created",
            actor=actor,
            detail_payload={},
        ))
        self.session.commit()
        self.session.refresh(entity)
        return entity

    def get(self, order_id: int):
        return self.session.get(TradingOrderEntity, order_id)

    def get_by_client_order_id(self, client_order_id: str):
        return self.session.scalar(
            select(TradingOrderEntity).where(
                TradingOrderEntity.client_order_id == client_order_id
            )
        )

    def list(self, account_id=None, status_code=None, exchange_code=None, symbol=None, limit=100, offset=0):
        stmt = select(TradingOrderEntity)
        if account_id is not None:
            stmt = stmt.where(TradingOrderEntity.account_id == account_id)
        if status_code:
            stmt = stmt.where(TradingOrderEntity.status_code == status_code.upper())
        if exchange_code:
            stmt = stmt.where(TradingOrderEntity.exchange_code == exchange_code.upper())
        if symbol:
            stmt = stmt.where(TradingOrderEntity.symbol == symbol.upper())
        return list(self.session.scalars(
            stmt.order_by(TradingOrderEntity.order_id.desc()).offset(offset).limit(limit)
        ))

    def history(self, order_id: int):
        return list(self.session.scalars(
            select(TradingOrderStatusHistoryEntity)
            .where(TradingOrderStatusHistoryEntity.order_id == order_id)
            .order_by(TradingOrderStatusHistoryEntity.order_status_history_id)
        ))
