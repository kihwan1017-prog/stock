from decimal import Decimal
from stock_platform.broker.kiwoom.mapper import KiwoomOrderMapper
from stock_platform.broker.models import BrokerOrderRequest, BrokerOrderSide, BrokerOrderType

def test_market_order_mapping():
    req = BrokerOrderRequest("KRX", "005930", BrokerOrderSide.BUY, BrokerOrderType.MARKET, Decimal("10"), None, "x")
    body = KiwoomOrderMapper.to_body(req, "MARKET_CODE", "LIMIT_CODE")
    assert body["stk_cd"] == "005930"
    assert body["ord_qty"] == "10"
    assert body["ord_uv"] == ""
    assert body["trde_tp"] == "MARKET_CODE"
