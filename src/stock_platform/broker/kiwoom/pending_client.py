from typing import Any
from stock_platform.broker.kiwoom.client import KiwoomRestClient

ACCOUNT_PATH = "/api/dostk/acnt"
ORDER_PATH = "/api/dostk/ordr"
PENDING_ORDER_API_ID = "ka10075"
MODIFY_ORDER_API_ID = "kt10002"
CANCEL_ORDER_API_ID = "kt10003"

class KiwoomPendingOrderClient:
    def __init__(self, client: KiwoomRestClient) -> None:
        self._client = client

    async def get_pending_orders(self, account_number: str) -> dict[str, Any]:
        return await self._client.post(
            path=ACCOUNT_PATH,
            api_id=PENDING_ORDER_API_ID,
            body={"acnt_no": account_number, "all_stk_tp": "0",
                  "trde_tp": "0", "dmst_stex_tp": "KRX"},
        )

    async def modify_order(self, *, original_order_id: str, symbol: str,
                           quantity: str, price: str, trade_type: str) -> dict[str, Any]:
        return await self._client.post(
            path=ORDER_PATH, api_id=MODIFY_ORDER_API_ID,
            body={"dmst_stex_tp": "KRX", "orig_ord_no": original_order_id,
                  "stk_cd": symbol, "mdfy_qty": quantity, "mdfy_uv": price,
                  "mdfy_cond_uv": "", "trde_tp": trade_type},
        )

    async def cancel_order(self, *, original_order_id: str, symbol: str,
                           quantity: str) -> dict[str, Any]:
        return await self._client.post(
            path=ORDER_PATH, api_id=CANCEL_ORDER_API_ID,
            body={"dmst_stex_tp": "KRX", "orig_ord_no": original_order_id,
                  "stk_cd": symbol, "cncl_qty": quantity},
        )
