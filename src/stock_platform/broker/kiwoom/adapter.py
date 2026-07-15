from stock_platform.broker.base import BrokerOrderAdapter
from stock_platform.broker.models import BrokerOrderRequest, BrokerOrderSide
from stock_platform.broker.kiwoom.endpoints import *
from stock_platform.broker.kiwoom.mapper import KiwoomOrderMapper

class KiwoomRestOrderAdapter(BrokerOrderAdapter):
    def __init__(self, config, client, market_trade_type: str, limit_trade_type: str):
        self.config, self.client = config, client
        self.market_trade_type, self.limit_trade_type = market_trade_type, limit_trade_type

    async def place_order(self, request: BrokerOrderRequest):
        if request.exchange_code.upper() != "KRX":
            raise ValueError("Kiwoom adapter supports KRX only")
        if not self.config.use_mock and not self.config.live_order_enabled:
            raise PermissionError("Kiwoom live order switch is disabled")
        data = await self.client.post(
            DOMESTIC_STOCK_ORDER_PATH,
            BUY_ORDER_API_ID if request.side == BrokerOrderSide.BUY else SELL_ORDER_API_ID,
            KiwoomOrderMapper.to_body(request, self.market_trade_type, self.limit_trade_type),
        )
        return KiwoomOrderMapper.to_response(request, data)

    async def cancel_order(self, broker_order_id: str):
        raise NotImplementedError("STEP28-4에서 연결합니다.")

    async def get_order(self, broker_order_id: str):
        raise NotImplementedError("STEP28-4에서 연결합니다.")

    async def get_account_snapshot(self):
        raise NotImplementedError("STEP28-3에서 연결합니다.")
