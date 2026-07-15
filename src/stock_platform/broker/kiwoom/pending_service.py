from sqlalchemy.orm import Session
from stock_platform.broker.kiwoom.pending_mapper import KiwoomPendingOrderMapper
from stock_platform.broker.pending_repository import BrokerPendingOrderRepository

class KiwoomPendingOrderService:
    def __init__(self, session: Session, client) -> None:
        self.client = client
        self.repo = BrokerPendingOrderRepository(session)

    async def synchronize(self, account_number: str):
        payload = await self.client.get_pending_orders(account_number)
        rows = KiwoomPendingOrderMapper.map_list(account_number, payload)
        count = self.repo.replace_for_account("KIWOOM", account_number, rows)
        return {"broker_code": "KIWOOM", "account_number": account_number,
                "pending_order_count": count}

    async def modify(self, **kwargs):
        return await self.client.modify_order(**kwargs)

    async def cancel(self, **kwargs):
        return await self.client.cancel_order(**kwargs)
