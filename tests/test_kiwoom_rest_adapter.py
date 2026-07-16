from decimal import Decimal
from stock_platform.broker.kiwoom.adapter import KiwoomBrokerAdapter
from stock_platform.broker.kiwoom.config import KiwoomOrderConfig
from stock_platform.broker.kiwoom.token_client import KiwoomAccessToken
from stock_platform.broker.models import BrokerOrderRequest
from datetime import datetime

class TokenClient:
    def issue(self):
        return KiwoomAccessToken("TOKEN", "bearer", datetime(2099, 1, 1))

class Response:
    def raise_for_status(self): pass
    def json(self):
        return {
            "return_code": 0,
            "return_msg": "정상",
            "ord_no": "1234567",
            "dmst_stex_tp": "KRX",
        }

class Client:
    def post(self, *args, **kwargs):
        return Response()

def test_submit_mock_order():
    config = KiwoomOrderConfig(
        base_url="https://mockapi.kiwoom.com",
        app_key="a",
        secret_key="s",
        use_mock=True,
        live_order_enabled=False,
    )
    adapter = KiwoomBrokerAdapter(config, Client(), TokenClient())
    result = adapter.submit_order(BrokerOrderRequest(
        client_order_id="ORD-1",
        account_id=1,
        exchange_code="KRX",
        symbol="005930",
        side="BUY",
        order_type="LIMIT",
        quantity=Decimal("1"),
        price=Decimal("70000"),
        time_in_force="DAY",
    ))
    assert result.accepted is True
    assert result.broker_order_id == "1234567"
