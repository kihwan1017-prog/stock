from decimal import Decimal
from stock_platform.broker.kiwoom.order_mapper import KiwoomOrderMapper
from stock_platform.broker.models import BrokerOrderRequest

def request(side="BUY", order_type="LIMIT", tif="DAY", price=Decimal("70000")):
    return BrokerOrderRequest(
        client_order_id="ORD-1",
        account_id=1,
        exchange_code="KRX",
        symbol="005930",
        side=side,
        order_type=order_type,
        quantity=Decimal("2"),
        price=price,
        time_in_force=tif,
    )

def test_buy_limit_mapping():
    req = request()
    assert KiwoomOrderMapper.api_id(req.side) == "kt10000"
    assert KiwoomOrderMapper.body(req) == {
        "dmst_stex_tp": "KRX",
        "stk_cd": "005930",
        "ord_qty": "2",
        "trde_tp": "0",
        "ord_uv": "70000",
    }

def test_sell_api_id():
    assert KiwoomOrderMapper.api_id("SELL") == "kt10001"

def test_market_mapping_has_no_price():
    body = KiwoomOrderMapper.body(
        request(order_type="MARKET", price=None)
    )
    assert body["trde_tp"] == "3"
    assert "ord_uv" not in body
