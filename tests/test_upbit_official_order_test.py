"""공식 Order Test + Controlled Smoke Gate (실주문 0)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.broker.upbit.order_client import UpbitOrderRestClient
from stock_platform.broker.upbit.rate_limit_constants import UpbitOperationType
from stock_platform.broker.upbit.rate_limit_http import infer_operation
from stock_platform.trading.controlled_live_order_smoke_service import (
    ControlledLiveOrderSmokeError,
    ControlledLiveOrderSmokeService,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    ORDER_TEST_TTL_SECONDS,
)


def _uba():
    return SimpleNamespace(
        user_broker_account_id=1380,
        user_id=1,
        broker_code="UPBIT",
        is_active=True,
        deleted_at=None,
        live_order_enabled=False,
        live_armed=False,
        connection_status="CONNECTED",
        masked_account_number="****1234",
        last_synced_at=datetime.now(timezone.utc),
        arm_expires_at=None,
    )


def test_infer_operation_separates_order_test_from_create() -> None:
    assert (
        infer_operation("POST", "/v1/orders/test")
        == UpbitOperationType.ORDER_TEST
    )
    assert (
        infer_operation("POST", "/v1/orders") == UpbitOperationType.ORDER_CREATE
    )


def test_order_client_test_create_order_endpoint() -> None:
    client = UpbitOrderRestClient.__new__(UpbitOrderRestClient)
    seen: dict = {}

    def fake_request(method, endpoint, **kwargs):
        seen["method"] = method
        seen["endpoint"] = endpoint
        seen["op"] = kwargs.get("operation")
        seen["body"] = kwargs.get("json_body")
        return {"uuid": "test-uuid", "side": "bid", "ord_type": "limit"}

    client._request = fake_request  # type: ignore[method-assign]
    out = client.test_create_order(
        {
            "market": "KRW-BTC",
            "side": "bid",
            "volume": "0.0001",
            "price": "100000000",
            "ord_type": "limit",
        }
    )
    assert seen["endpoint"] == "/v1/orders/test"
    assert seen["op"] == UpbitOperationType.ORDER_TEST
    assert out["uuid"] == "test-uuid"


def test_order_test_pass_without_create_order() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    svc = ControlledLiveOrderSmokeService(session)

    class FakeClient:
        def __init__(self) -> None:
            self.create_calls = 0
            self.test_calls = 0

        def get_order_chance(self, *, market: str):
            return {
                "bid_fee": "0.0005",
                "ask_fee": "0.0005",
                "market": {
                    "id": market,
                    "bid": {"min_total": "5000", "currency": "KRW"},
                },
                "bid_account": {"balance": "100000"},
            }

        def create_order(self, body):
            self.create_calls += 1
            raise AssertionError("create_order must not be called")

        def test_create_order(self, body):
            self.test_calls += 1
            assert body["market"] == "KRW-BTC"
            assert body["side"] == "bid"
            assert body["ord_type"] == "price"
            assert body["price"] == "5000"
            assert "volume" not in body
            return {"uuid": "t1", "side": "bid", "ord_type": "price"}

    fake = FakeClient()
    with patch(
        "stock_platform.trading.controlled_live_order_smoke_service.emit_live_safety_audit"
    ):
        out = svc.order_test(
            uba_id=1380,
            user_id=1,
            actor="t",
            market="KRW-BTC",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=None,
            order_type="MARKET",
            order_client=fake,
            reference_price=Decimal("100000000"),
        )
    assert out["test_passed"] is True
    assert out["status"] == "ORDER_TEST_PASSED"
    assert out["adapter_create_order_calls"] == 0
    assert fake.create_calls == 0
    assert fake.test_calls == 1
    assert out["minimum_order_amount"] == "5000"
    assert out["request"]["ord_type"] == "price"
    assert out["diagnostics"]["volume_present"] is False
    assert "volume" not in out["diagnostics"]["query_string_for_hash"]


def test_order_test_error_surface() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    svc = ControlledLiveOrderSmokeService(session)

    class FakeClient:
        def get_order_chance(self, *, market: str):
            return {
                "market": {"id": market, "bid": {"min_total": "5000"}},
                "bid_fee": "0.0005",
            }

        def create_order(self, body):
            raise AssertionError("no create")

        def test_create_order(self, body):
            raise RuntimeError("market_offline")

    with patch(
        "stock_platform.trading.controlled_live_order_smoke_service.emit_live_safety_audit"
    ):
        out = svc.order_test(
            uba_id=1380,
            user_id=1,
            actor="t",
            market="KRW-BTC",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=None,
            order_type="MARKET",
            order_client=FakeClient(),
            reference_price=Decimal("100000000"),
        )
    assert out["test_passed"] is False
    assert out["status"] == "ORDER_TEST_FAILED"
    assert any("order_test:" in e for e in out["validation_errors"])


def test_live_confirm_blocked_without_order_test() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    svc = ControlledLiveOrderSmokeService(session)
    with (
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.UpbitLiveSmokeService.execute"
        ) as execute,
    ):
        try:
            svc.confirm(
                uba_id=1380,
                user_id=1,
                actor="t",
                market="KRW-BTC",
                side="BUY",
                amount=Decimal("5000"),
                limit_price=Decimal("100000000"),
                confirmation_text="UPBIT LIVE BUY CONFIRM",
                arm_token="tok",
                execute_live=True,
            )
            raised = False
        except ControlledLiveOrderSmokeError as exc:
            raised = True
            assert str(exc) == "ORDER_TEST_REQUIRED"
    assert raised
    execute.assert_not_called()


def test_order_test_stale_on_input_change() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    svc = ControlledLiveOrderSmokeService(session)
    fp = svc.build_order_test_fingerprint(
        uba_id=1380,
        market="KRW-BTC",
        side="BUY",
        ord_type="limit",
        volume="0.00005",
        price="100000000",
        amount="5000",
    )
    with patch(
        "stock_platform.trading.controlled_live_order_smoke_service.emit_live_safety_audit"
    ):
        try:
            svc.confirm(
                uba_id=1380,
                user_id=1,
                actor="t",
                market="KRW-BTC",
                side="BUY",
                amount=Decimal("6000"),  # 변경
                limit_price=Decimal("100000000"),
                confirmation_text="UPBIT LIVE BUY CONFIRM",
                arm_token="tok",
                execute_live=True,
                order_test_fingerprint=fp,
                order_test_tested_at=datetime.now(timezone.utc).isoformat(),
            )
            raised = False
        except ControlledLiveOrderSmokeError as exc:
            raised = True
            assert str(exc) == "ORDER_TEST_STALE_INPUT_CHANGED"
    assert raised


def test_sell_without_smoke_buy_blocked() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    svc = ControlledLiveOrderSmokeService(session)
    with patch(
        "stock_platform.trading.controlled_live_order_smoke_service.emit_live_safety_audit"
    ):
        try:
            svc.order_test(
                uba_id=1380,
                user_id=1,
                actor="t",
                market="KRW-BTC",
                side="SELL",
                amount=Decimal("5000"),
                limit_price=Decimal("100000000"),
                skip_network=True,
            )
            raised = False
        except ControlledLiveOrderSmokeError as exc:
            raised = True
            assert str(exc) == "EXISTING_POSITION_SELL_BLOCKED"
    assert raised


def test_runtime_running_blocks_order_test() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    svc = ControlledLiveOrderSmokeService(session)
    with (
        patch(
            "stock_platform.realtime.runtime.realtime_execution_runner.status",
            return_value={"running": True},
        ),
        patch(
            "stock_platform.realtime.runtime.realtime_strategy_runner.status",
            return_value={"running": False},
        ),
    ):
        try:
            svc.order_test(
                uba_id=1380,
                user_id=1,
                actor="t",
                market="KRW-BTC",
                side="BUY",
                amount=Decimal("5000"),
                limit_price=Decimal("100000000"),
                skip_network=True,
            )
            raised = False
        except ControlledLiveOrderSmokeError as exc:
            raised = True
            assert str(exc) == "RUNTIME_RUNNING"
    assert raised


def test_order_test_ttl_constant() -> None:
    assert ORDER_TEST_TTL_SECONDS == 60
    now = datetime.now(timezone.utc)
    expired = now - timedelta(seconds=ORDER_TEST_TTL_SECONDS + 1)
    from stock_platform.operation.runtime_preflight_service import (
        evaluate_preflight_freshness,
    )

    fr = evaluate_preflight_freshness(
        expired.isoformat(), now=now, ttl_seconds=ORDER_TEST_TTL_SECONDS
    )
    assert fr["fresh"] is False
