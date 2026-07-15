from __future__ import annotations

from typing import Any

from stock_platform.broker.kiwoom.client import KiwoomRestClient


ACCOUNT_PATH = "/api/dostk/acnt"
ACCOUNT_NUMBER_API_ID = "ka00001"
DEPOSIT_DETAIL_API_ID = "kt00001"
ACCOUNT_BALANCE_API_ID = "kt00018"


class KiwoomAccountClient:
    """키움 계좌번호·예수금·계좌평가잔고 조회."""

    def __init__(self, client: KiwoomRestClient) -> None:
        self._client = client

    async def get_account_number(self) -> str:
        payload = await self._client.post(
            path=ACCOUNT_PATH,
            api_id=ACCOUNT_NUMBER_API_ID,
            body={},
        )
        account_number = str(
            payload.get("acctNo")
            or payload.get("acct_no")
            or ""
        ).strip()

        if not account_number:
            raise ValueError(
                "Kiwoom account response has no account number"
            )

        return account_number

    async def get_deposit_detail(
        self,
        *,
        query_type: str = "3",
    ) -> dict[str, Any]:
        return await self._client.post(
            path=ACCOUNT_PATH,
            api_id=DEPOSIT_DETAIL_API_ID,
            body={"qry_tp": query_type},
        )

    async def get_account_balance(
        self,
        *,
        query_type: str = "1",
        exchange_type: str = "KRX",
    ) -> dict[str, Any]:
        return await self._client.post(
            path=ACCOUNT_PATH,
            api_id=ACCOUNT_BALANCE_API_ID,
            body={
                "qry_tp": query_type,
                "dmst_stex_tp": exchange_type,
            },
        )
