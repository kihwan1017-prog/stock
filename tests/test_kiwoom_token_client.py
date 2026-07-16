from stock_platform.broker.kiwoom.config import KiwoomOrderConfig
from stock_platform.broker.kiwoom.token_client import KiwoomTokenClient

class Response:
    def raise_for_status(self): pass
    def json(self):
        return {
            "return_code": 0,
            "return_msg": "정상적으로 처리되었습니다",
            "token_type": "bearer",
            "token": "TOKEN",
            "expires_dt": "20261231235959",
        }

class Client:
    def post(self, *args, **kwargs):
        return Response()

def test_issue_token():
    config = KiwoomOrderConfig(
        base_url="https://mockapi.kiwoom.com",
        app_key="a",
        secret_key="s",
        use_mock=True,
        live_order_enabled=False,
    )
    token = KiwoomTokenClient(config, Client()).issue()
    assert token.token == "TOKEN"
