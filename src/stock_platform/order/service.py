from decimal import Decimal
from sqlalchemy.orm import Session
from stock_platform.order.id_generator import ClientOrderIdGenerator
from stock_platform.order.models import CreateOrderCommand, OrderType
from stock_platform.order.repository import TradingOrderRepository

class TradingOrderService:
    def __init__(self, session: Session):
        self.repository = TradingOrderRepository(session)

    def create(self, command: CreateOrderCommand, actor: str = "SYSTEM"):
        self._validate(command)
        client_order_id = command.client_order_id or ClientOrderIdGenerator.generate()
        if self.repository.get_by_client_order_id(client_order_id):
            raise ValueError("client_order_id already exists")
        return self.repository.create(command, client_order_id, actor)

    @staticmethod
    def _validate(command: CreateOrderCommand):
        if command.account_id <= 0:
            raise ValueError("account_id must be greater than zero")
        if command.quantity <= Decimal("0"):
            raise ValueError("quantity must be greater than zero")
        if not command.broker_code.strip() or not command.exchange_code.strip() or not command.symbol.strip():
            raise ValueError("broker_code, exchange_code and symbol are required")
        if command.order_type == OrderType.LIMIT and (command.price is None or command.price <= Decimal("0")):
            raise ValueError("LIMIT order requires price > 0")
