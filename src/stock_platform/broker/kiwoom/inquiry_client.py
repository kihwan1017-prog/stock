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


class KiwoomInquiryError(RuntimeError):
    """키움 조회 TR 실패 (return_code != 0 또는 필수 파라미터 오류)."""

    def __init__(
        self,
        *,
        api_id: str,
        return_code: Any,
        return_msg: str,
    ) -> None:
        self.api_id = api_id
        self.return_code = return_code
        self.return_msg = return_msg
        super().__init__(
            f"Kiwoom inquiry {api_id} failed: "
            f"return_code={return_code} msg={return_msg}"
        )


class KiwoomOrderInquiryClient:
    ACCOUNT_PATH = "/api/dostk/acnt"
    PENDING_API_ID = "ka10075"
    EXECUTION_API_ID = "ka10076"

    # ka10075 필수: all_stk_tp / trde_tp / stex_tp
    _DEFAULT_PENDING_BODY = {
        "all_stk_tp": "0",
        "trde_tp": "0",
        "stex_tp": "0",
    }
    # ka10076 필수: qry_tp / sell_tp / stex_tp
    _DEFAULT_EXECUTION_BODY = {
        "qry_tp": "0",
        "sell_tp": "0",
        "stex_tp": "0",
    }

    def __init__(
        self,
        rest_client: KiwoomRestClient,
    ) -> None:
        # async account client(client.KiwoomRestClient) 오주입 방지
        post = getattr(rest_client, "post", None)
        if post is None:
            raise TypeError(
                "KiwoomOrderInquiryClient requires a RestClient with post()"
            )
        try:
            import inspect

            params = inspect.signature(post).parameters
        except (TypeError, ValueError):
            params = {}
        if "request_type" not in params:
            raise TypeError(
                "KiwoomOrderInquiryClient requires sync http_client."
                "KiwoomRestClient (post(..., request_type=...)); "
                "async account client.KiwoomRestClient is not supported"
            )
        self._rest_client = rest_client

    def get_pending_orders(
        self,
        *,
        account_number: str,
        continuation_key: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> KiwoomInquiryPage:
        # account_number는 토큰 계좌 기준 — body 필수 아님. 하위 호환용 유지.
        _ = account_number
        body = {
            **self._DEFAULT_PENDING_BODY,
            **(extra_body or {}),
        }

        payload, headers = self._rest_client.post(
            path=self.ACCOUNT_PATH,
            api_id=self.PENDING_API_ID,
            body=body,
            request_type="INQUIRY",
            continuation_key=continuation_key,
        )
        self._ensure_ok(self.PENDING_API_ID, payload)

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
        _ = account_number
        body = {
            **self._DEFAULT_EXECUTION_BODY,
            **(extra_body or {}),
        }

        payload, headers = self._rest_client.post(
            path=self.ACCOUNT_PATH,
            api_id=self.EXECUTION_API_ID,
            body=body,
            request_type="INQUIRY",
            continuation_key=continuation_key,
        )
        self._ensure_ok(self.EXECUTION_API_ID, payload)

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
    def _ensure_ok(api_id: str, payload: dict[str, Any]) -> None:
        """return_code가 있으면 0만 허용. 빈 목록과 API 오류를 구분."""

        if "return_code" not in payload:
            return
        code = payload.get("return_code")
        try:
            code_int = int(code)
        except (TypeError, ValueError):
            code_int = -1
        if code_int == 0:
            return
        raise KiwoomInquiryError(
            api_id=api_id,
            return_code=code,
            return_msg=str(
                payload.get("return_msg")
                or payload.get("message")
                or ""
            ),
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
