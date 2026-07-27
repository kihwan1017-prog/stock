"""STEP 8-5-19 — KiwoomBrokerAdapter mock submit (UBA 필수)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.broker.kiwoom.adapter import KiwoomBrokerAdapter
from stock_platform.broker.kiwoom.config import KiwoomOrderConfig
from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
)


class FakeRestClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def post(self, *, path, api_id, body, request_type):
        self.calls.append(
            {
                "path": path,
                "api_id": api_id,
                "body": body,
                "request_type": request_type,
            }
        )
        return (
            {
                "return_code": 0,
                "ord_no": "MOCK-ORD-1",
                "return_msg": "OK",
            },
            {},
        )


def test_submit_mock_order() -> None:
    rest = FakeRestClient()
    adapter = KiwoomBrokerAdapter(
        config=KiwoomOrderConfig(
            base_url="https://mockapi.kiwoom.com",
            app_key="test-key",
            secret_key="test-secret",
            use_mock=True,
            live_order_enabled=False,
        ),
        rest_client=rest,
    )

    request = BrokerOrderRequest(
        client_order_id="cid-1",
        exchange_code="KRX",
        symbol="005930",
        side=BrokerOrderSide.BUY,
        order_type=BrokerOrderType.LIMIT,
        quantity=Decimal("1"),
        price=Decimal("70000"),
        account_type="LIVE",
        broker_code="KIWOOM",
        user_broker_account_id=99,
        owner_user_id=1,
        external_account_ref="******7890",
        credential_ref="USER_BROKER_ACCOUNT:99",
    )

    result = adapter.submit_order(request)

    assert result.accepted is True
    assert result.status == BrokerOrderStatus.ACCEPTED
    assert result.broker_order_id == "MOCK-ORD-1"
    assert isinstance(result.submitted_at, datetime)
    assert result.submitted_at.tzinfo is not None
    assert len(rest.calls) == 1
    assert rest.calls[0]["api_id"] == "kt10000"
    assert "acct" not in str(rest.calls[0]["body"]).lower()
    # 원문 계좌번호 미포함
    assert "1234567890" not in str(rest.calls[0])


def test_submit_live_without_uba_fails() -> None:
    adapter = KiwoomBrokerAdapter(
        config=KiwoomOrderConfig(
            base_url="https://mockapi.kiwoom.com",
            app_key="test-key",
            secret_key="test-secret",
            use_mock=True,
            live_order_enabled=False,
        ),
        rest_client=FakeRestClient(),
    )
    request = BrokerOrderRequest(
        client_order_id="cid-2",
        exchange_code="KRX",
        symbol="005930",
        side=BrokerOrderSide.BUY,
        order_type=BrokerOrderType.MARKET,
        quantity=Decimal("1"),
        account_type="LIVE",
        broker_code="KIWOOM",
        user_broker_account_id=None,
    )
    try:
        adapter.submit_order(request)
        raise AssertionError("expected PermissionError")
    except PermissionError as exc:
        assert "user_broker_account_id" in str(exc)
