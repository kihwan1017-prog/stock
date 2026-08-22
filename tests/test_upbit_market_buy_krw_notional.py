"""Upbit MARKET BUY: price = 총 KRW notional (ticker 금지)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderSide,
    BrokerOrderType,
)
from stock_platform.broker.upbit.order_mapper import UpbitOrderMapper
from stock_platform.broker.upbit.rules import (
    UPBIT_MIN_NOTIONAL_KRW,
    round_upbit_krw_notional,
)
from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.order.outbox_dispatcher import OrderOutboxDispatcher


def test_market_buy_5000_payload() -> None:
    body = UpbitOrderMapper.body(
        BrokerOrderRequest(
            client_order_id="MB1",
            exchange_code="UPBIT",
            symbol="KRW-BTC",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("0.01"),
            price=Decimal("5000"),
            quote_amount_krw=Decimal("5000"),
            reference_price=Decimal("3710"),
        )
    )
    assert body["side"] == "bid"
    assert body["ord_type"] == "price"
    assert body["price"] == "5000"
    assert "volume" not in body


def test_market_buy_10000_payload() -> None:
    body = UpbitOrderMapper.body(
        BrokerOrderRequest(
            client_order_id="MB2",
            exchange_code="UPBIT",
            symbol="KRW-ETH",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("1"),
            quote_amount_krw=Decimal("10000"),
            # ticker를 price에 넣어도 quote_amount_krw 우선
            price=Decimal("3710"),
            reference_price=Decimal("3710"),
        )
    )
    assert body["ord_type"] == "price"
    assert body["price"] == "10000"
    assert "volume" not in body


def test_market_buy_below_minimum_blocks_before_broker() -> None:
    with pytest.raises(ValueError, match="minimum"):
        UpbitOrderMapper.body(
            BrokerOrderRequest(
                client_order_id="MB3",
                exchange_code="UPBIT",
                symbol="KRW-BTC",
                side=BrokerOrderSide.BUY,
                order_type=BrokerOrderType.MARKET,
                quantity=Decimal("1"),
                quote_amount_krw=Decimal("4999"),
            )
        )


def test_limit_buy_unit_price_and_volume() -> None:
    body = UpbitOrderMapper.body(
        BrokerOrderRequest(
            client_order_id="LB1",
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
    assert "price" in body
    assert "volume" in body
    assert Decimal(body["volume"]) == Decimal("0.001")


def test_market_sell_volume_only() -> None:
    body = UpbitOrderMapper.body(
        BrokerOrderRequest(
            client_order_id="MS1",
            exchange_code="UPBIT",
            symbol="KRW-BTC",
            side=BrokerOrderSide.SELL,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("0.5"),
            price=None,
        )
    )
    assert body["ord_type"] == "market"
    assert body["side"] == "ask"
    assert Decimal(body["volume"]) == Decimal("0.5")
    assert "price" not in body


def test_limit_sell_price_and_volume() -> None:
    body = UpbitOrderMapper.body(
        BrokerOrderRequest(
            client_order_id="LS1",
            exchange_code="UPBIT",
            symbol="KRW-BTC",
            side=BrokerOrderSide.SELL,
            order_type=BrokerOrderType.LIMIT,
            quantity=Decimal("0.01"),
            price=Decimal("150000000"),
        )
    )
    assert body["ord_type"] == "limit"
    assert body["side"] == "ask"
    assert "price" in body
    assert "volume" in body


def test_krw_notional_decimal_floor_keeps_min_boundary() -> None:
    # 5000.9 → 5000 (원 단위 내림), 최소 미만으로 떨어지지 않음
    assert round_upbit_krw_notional(Decimal("5000.9")) == Decimal("5000")
    assert round_upbit_krw_notional(Decimal("5000")) == Decimal("5000")
    # 4999.9 → 4999 (의도적으로 min 미만 — 호출측에서 BLOCK)
    assert round_upbit_krw_notional(Decimal("4999.9")) == Decimal("4999")
    assert UPBIT_MIN_NOTIONAL_KRW == Decimal("5000")


def test_oes_market_buy_price_is_krw_not_ticker() -> None:
    service = OrderExecutionService.__new__(OrderExecutionService)
    qty, price, meta = service._resolve_size(
        OrderExecutionCommand(
            account_id=None,
            broker_code="UPBIT",
            exchange_code="UPBIT",
            symbol="KRW-PROM",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            price=Decimal("3710"),  # ticker — broker price 금지
            order_amount=Decimal("5000"),
            reference_price=Decimal("3710"),
        )
    )
    assert price == Decimal("5000")
    assert qty > 0
    assert meta is not None
    assert meta["quote_amount_krw"] == "5000"
    assert meta["reference_price"] == "3710"
    assert meta["broker_price_semantics"] == "UPBIT_MARKET_BUY_KRW_NOTIONAL"


def test_oes_market_buy_below_min_blocked() -> None:
    service = OrderExecutionService.__new__(OrderExecutionService)
    with pytest.raises(ValueError, match="minimum"):
        service._resolve_size(
            OrderExecutionCommand(
                account_id=None,
                broker_code="UPBIT",
                exchange_code="UPBIT",
                symbol="KRW-BTC",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                price=Decimal("100"),
                order_amount=Decimal("4000"),
                reference_price=Decimal("100"),
            )
        )


def test_oes_kiwoom_market_still_uses_unit_reference() -> None:
    """KIWOOM MARKET는 KRW notional 의미로 바꾸지 않는다."""
    service = OrderExecutionService.__new__(OrderExecutionService)
    qty, price, _meta = service._resolve_size(
        OrderExecutionCommand(
            account_id=1,
            broker_code="KIWOOM",
            exchange_code="KRX",
            symbol="005930",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            price=Decimal("70000"),
            quantity=Decimal("1"),
        )
    )
    assert qty == Decimal("1")
    assert price == Decimal("70000")


def test_outbox_roundtrip_preserves_quote_amount_krw() -> None:
    """Outbox payload → BrokerOrderRequest → mapper 후에도 KRW 유지."""
    request = OrderOutboxDispatcher._to_order_request(
        {
            "client_order_id": "CLIENT-MB",
            "account_id": 1,
            "broker_code": "UPBIT",
            "environment": "PAPER",
            "exchange_code": "UPBIT",
            "symbol": "KRW-PROM",
            "side": "BUY",
            "order_type": "MARKET",
            "quantity": "1.348",
            "price": "5000",
            "quote_amount_krw": "5000",
            "reference_price": "3710",
            "time_in_force": "DAY",
        }
    )
    assert request.quote_amount_krw == Decimal("5000")
    assert request.reference_price == Decimal("3710")
    assert request.price == Decimal("5000")
    body = UpbitOrderMapper.body(request)
    assert body["price"] == "5000"
    assert body["ord_type"] == "price"
    assert "volume" not in body
    # ticker가 broker price로 쓰이지 않음
    assert body["price"] != "3710"

def test_mock_e2e_ticker_not_used_as_broker_price() -> None:
    """Sizing → mapper: ticker=3710 이어도 broker price=5000."""
    service = OrderExecutionService.__new__(OrderExecutionService)
    _qty, krw_price, meta = service._resolve_size(
        OrderExecutionCommand(
            account_id=None,
            broker_code="UPBIT",
            exchange_code="UPBIT",
            symbol="KRW-PROM",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            price=Decimal("3710"),
            order_amount=Decimal("5000"),
            reference_price=Decimal("3710"),
        )
    )
    body = UpbitOrderMapper.body(
        BrokerOrderRequest(
            client_order_id="E2E1",
            exchange_code="UPBIT",
            symbol="KRW-PROM",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=_qty,
            price=krw_price,
            quote_amount_krw=Decimal(meta["quote_amount_krw"]),
            reference_price=Decimal(meta["reference_price"]),
        )
    )
    assert body["price"] == "5000"
    assert body["price"] != "3710"
    assert body["ord_type"] == "price"
