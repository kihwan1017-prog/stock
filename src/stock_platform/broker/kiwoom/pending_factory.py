from stock_platform.broker.kiwoom.account_factory import build_kiwoom_account_client
from stock_platform.broker.kiwoom.pending_client import KiwoomPendingOrderClient

def build_kiwoom_pending_order_client():
    account_client = build_kiwoom_account_client()
    return KiwoomPendingOrderClient(account_client._client)
