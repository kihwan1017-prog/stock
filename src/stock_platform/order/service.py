from decimal import Decimal
from sqlalchemy.orm import Session
from stock_platform.order.id_generator import ClientOrderIdGenerator
from stock_platform.order.models import CreateOrderCommand, OrderType
from stock_platform.order.repository import TradingOrderRepository

class TradingOrderService:
    def __init__(self, session: Session):
        self.repository = TradingOrderRepository(session)

    def create(
        self,
        command: CreateOrderCommand,
        actor: str = "SYSTEM",
        *,
        commit: bool = True,
    ):
        self._validate(command)
        client_order_id = command.client_order_id or ClientOrderIdGenerator.generate()
        if self.repository.get_by_client_order_id(client_order_id):
            raise ValueError("client_order_id already exists")
        return self.repository.create(
            command,
            client_order_id,
            actor,
            commit=commit,
        )

    @staticmethod
    def _validate(command: CreateOrderCommand):
        # Paper XOR LIVE — 혼용 금지
        uba = command.user_broker_account_id
        paper_id = command.account_id
        if uba is not None:
            if int(uba) <= 0:
                raise ValueError("user_broker_account_id must be greater than zero")
            if paper_id is not None:
                raise ValueError(
                    "LIVE/UBA orders must not set paper account_id"
                )
        else:
            if paper_id is None or int(paper_id) <= 0:
                raise ValueError("account_id must be greater than zero")
        if command.quantity <= Decimal("0"):
            raise ValueError("quantity must be greater than zero")
        if not command.broker_code.strip() or not command.exchange_code.strip() or not command.symbol.strip():
            raise ValueError("broker_code, exchange_code and symbol are required")
        if command.order_type == OrderType.LIMIT and (command.price is None or command.price <= Decimal("0")):
            raise ValueError("LIMIT order requires price > 0")
