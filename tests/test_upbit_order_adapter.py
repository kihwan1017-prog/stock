"""업비트 주문 어댑터·규칙·outbox 라우팅 테스트 (STEP3–4)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from stock_platform.broker.factory import BrokerAdapterFactory
from stock_platform.broker.fee_policy import (
    UpbitFeePolicy,
    fee_policy_for_exchange,
)
from stock_platform.broker.models import (
    BrokerEnvironment,
    BrokerOrderRequest,
    BrokerOrderSide,
    BrokerOrderType,
)
from stock_platform.broker.paper.adapter import PaperBrokerAdapter
from stock_platform.broker.upbit.adapter import UpbitBrokerAdapter
from stock_platform.broker.upbit.order_mapper import UpbitOrderMapper
from stock_platform.broker.upbit.rules import (
    UPBIT_MIN_NOTIONAL_KRW,
    validate_upbit_notional,
)
from stock_platform.common.settings import Settings
from stock_platform.order.outbox_adapter_resolver import (
    resolve_outbox_adapter,
)
from stock_platform.order.outbox_dispatcher import (
    OrderOutboxDispatcher,
)
from stock_platform.position.lot_rounding import (
    round_price_to_tick,
    round_share_quantity,
)


def _mock_settings(**kwargs) -> Settings:
    base = dict(
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
        upbit_use_mock=True,
        upbit_live_order_enabled=False,
        global_live_order_enabled=False,
        upbit_allowed_markets="",
    )
    base.update(kwargs)
    return Settings(**base)


def test_upbit_limit_order_body() -> None:
    body = UpbitOrderMapper.body(
        BrokerOrderRequest(
            client_order_id="C1",
            exchange_code="UPBIT",
            symbol="KRW-BTC",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.LIMIT,
            quantity=Decimal("0.001"),
            price=Decimal("100000000"),
        )
    )
    assert body["ord_type"] == "limit"
    assert body["side"] == "bid"
    assert body["market"] == "KRW-BTC"


def test_upbit_market_buy_uses_price_ord_type() -> None:
    body = UpbitOrderMapper.body(
        BrokerOrderRequest(
            client_order_id="C2",
            exchange_code="UPBIT",
            symbol="BTC",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("1"),
            price=Decimal("10000"),
        )
    )
    assert body["ord_type"] == "price"
    assert "volume" not in body
    assert body["price"] == "10000"


def test_upbit_market_sell_uses_market_ord_type() -> None:
    body = UpbitOrderMapper.body(
        BrokerOrderRequest(
            client_order_id="C3",
            exchange_code="UPBIT",
            symbol="KRW-ETH",
            side=BrokerOrderSide.SELL,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("0.5"),
            price=None,
        )
    )
    assert body["ord_type"] == "market"
    assert Decimal(body["volume"]) == Decimal("0.5")


def test_min_notional_rejects() -> None:
    with pytest.raises(ValueError, match="minimum"):
        validate_upbit_notional(
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal("0.001"),
            price=Decimal("1000"),
        )


def test_upbit_adapter_mock_submit() -> None:
    adapter = UpbitBrokerAdapter(settings=_mock_settings())
    result = adapter.submit_order(
        BrokerOrderRequest(
            client_order_id="C4",
            exchange_code="UPBIT",
            symbol="KRW-BTC",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.LIMIT,
            quantity=Decimal("0.01"),
            price=Decimal("100000000"),
        )
    )
    assert result.accepted is True
    assert result.broker_order_id.startswith("UPBIT-MOCK-")


def test_factory_paper_upbit_returns_upbit_adapter() -> None:
    adapter = BrokerAdapterFactory.create(
        BrokerEnvironment.PAPER,
        "UPBIT",
    )
    assert isinstance(adapter, UpbitBrokerAdapter)


def test_factory_paper_kiwoom_stays_paper() -> None:
    adapter = BrokerAdapterFactory.create(
        BrokerEnvironment.PAPER,
        "KIWOOM",
    )
    assert isinstance(adapter, PaperBrokerAdapter)


def test_factory_live_upbit_requires_global_gate(monkeypatch) -> None:
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("UPBIT_USE_MOCK", "false")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(PermissionError, match="GLOBAL_LIVE"):
            BrokerAdapterFactory.create(
                BrokerEnvironment.LIVE,
                "UPBIT",
                session=MagicMock(),
            )
    finally:
        get_settings.cache_clear()


def test_resolve_outbox_adapter_upbit_paper() -> None:
    adapter = resolve_outbox_adapter(
        {"broker_code": "UPBIT", "environment": "PAPER"},
    )
    assert isinstance(adapter, UpbitBrokerAdapter)


def test_outbox_dispatch_routes_upbit_mock() -> None:
    result = OrderOutboxDispatcher(
        PaperBrokerAdapter()
    ).dispatch(
        event_type="SUBMIT_ORDER",
        idempotency_key="UPBIT-1",
        payload={
            "client_order_id": "CLIENT-U1",
            "account_id": 1,
            "broker_code": "UPBIT",
            "environment": "PAPER",
            "exchange_code": "UPBIT",
            "symbol": "KRW-BTC",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": "0.01",
            "price": "100000000",
            "time_in_force": "DAY",
        },
    )
    assert result["accepted"] is True
    assert str(result["broker_order_id"]).startswith("UPBIT-MOCK-")


def test_lot_rounding_upbit() -> None:
    assert round_share_quantity(
        Decimal("1.234567891"),
        exchange_code="UPBIT",
    ) == Decimal("1.23456789")
    price = round_price_to_tick(
        Decimal("12345"),
        exchange_code="UPBIT",
    )
    assert price % Decimal("10") == 0


def test_fee_policy_upbit() -> None:
    policy = fee_policy_for_exchange("UPBIT")
    assert isinstance(policy, UpbitFeePolicy)
    fee = policy.fee_amount(notional=Decimal("1000000"))
    assert fee == Decimal("500.0000")


def test_min_notional_constant() -> None:
    assert UPBIT_MIN_NOTIONAL_KRW == Decimal("5000")
