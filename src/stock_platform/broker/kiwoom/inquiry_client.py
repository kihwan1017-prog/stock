from __future__ import annotations

from typing import Any

from stock_platform.broker.kiwoom.http_client import (
    KiwoomRestClient,
)
from stock_platform.broker.kiwoom.inquiry_mapper import (
    KiwoomInquiryMapper,
)
from stock_platform.broker.kiwoom.inquiry_models import (
    KiwoomInquiryPage,
)


class KiwoomOrderInquiryClient:
    ACCOUNT_PATH = "/api/dostk/acnt"
    PENDING_API_ID = "ka10075"
    EXECUTION_API_ID = "ka10076"

    def __init__(
        self,
        rest_client: KiwoomRestClient,
    ) -> None:
        self._rest_client = rest_client

    def get_pending_orders(
        self,
        *,
        account_number: str,
        continuation_key: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> KiwoomInquiryPage:
        body = {
            "account_no": account_number,
            **(extra_body or {}),
        }

        payload, headers = self._rest_client.post(
            path=self.ACCOUNT_PATH,
            api_id=self.PENDING_API_ID,
            body=body,
            request_type="INQUIRY",
            continuation_key=continuation_key,
        )

        items = self._extract_items(
            payload,
            preferred_keys=(
                "oso",
                "output",
                "list",
                "data",
            ),
        )

        return KiwoomInquiryPage(
            items=[
                KiwoomInquiryMapper.pending_order(item)
                for item in items
            ],
            has_next=(
                headers.get("cont-yn", "").upper()
                == "Y"
            ),
            next_key=headers.get("next-key"),
        )

    def get_executions(
        self,
        *,
        account_number: str,
        continuation_key: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> KiwoomInquiryPage:
        body = {
            "account_no": account_number,
            **(extra_body or {}),
        }

        payload, headers = self._rest_client.post(
            path=self.ACCOUNT_PATH,
            api_id=self.EXECUTION_API_ID,
            body=body,
            request_type="INQUIRY",
            continuation_key=continuation_key,
        )

        items = self._extract_items(
            payload,
            preferred_keys=(
                "cntr",
                "output",
                "list",
                "data",
            ),
        )

        return KiwoomInquiryPage(
            items=[
                KiwoomInquiryMapper.execution(item)
                for item in items
            ],
            has_next=(
                headers.get("cont-yn", "").upper()
                == "Y"
            ),
            next_key=headers.get("next-key"),
        )

    @staticmethod
    def _extract_items(
        payload: dict[str, Any],
        *,
        preferred_keys: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        for key in preferred_keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [
                    item
                    for item in value
                    if isinstance(item, dict)
                ]

        for value in payload.values():
            if (
                isinstance(value, list)
                and all(
                    isinstance(item, dict)
                    for item in value
                )
            ):
                return value

        return []
