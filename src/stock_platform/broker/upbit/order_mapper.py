from __future__ import annotations

from decimal import Decimal
from typing import Any

from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderSide,
    BrokerOrderType,
)
from stock_platform.broker.upbit.rules import (
    round_upbit_krw_notional,
    round_upbit_price,
    round_upbit_volume,
    validate_upbit_notional,
)


class UpbitOrderMapper:
    """BrokerOrderRequest → Upbit POST /v1/orders 바디."""

    @classmethod
    def market(cls, request: BrokerOrderRequest) -> str:
        """심볼을 KRW-BTC 형식으로 정규화."""

        symbol = (request.symbol or "").strip().upper()
        exchange = (request.exchange_code or "").strip().upper()
        if "-" in symbol:
            return symbol
        if exchange in {"UPBIT", "KRW"} or not exchange:
            return f"KRW-{symbol}"
        return f"{exchange}-{symbol}"

    @classmethod
    def body(cls, request: BrokerOrderRequest) -> dict[str, Any]:
        market = cls.market(request)
        side = cls._side(request.side)
        order_type = (
            request.order_type
            if isinstance(request.order_type, str)
            else request.order_type.value
        ).upper()
        side_code = (
            request.side
            if isinstance(request.side, str)
            else request.side.value
        ).upper()

        qty = round_upbit_volume(Decimal(str(request.quantity)))

        if order_type == BrokerOrderType.MARKET.value or order_type == "MARKET":
            if side_code == BrokerOrderSide.BUY.value or side_code == "BUY":
                # MARKET BUY: price = TOTAL KRW NOTIONAL (ticker 금지)
                krw_raw = (
                    request.quote_amount_krw
                    if request.quote_amount_krw is not None
                    else request.price
                )
                if krw_raw is None or Decimal(str(krw_raw)) <= 0:
                    raise ValueError(
                        "Upbit market BUY requires KRW amount "
                        "(quote_amount_krw or price as notional)"
                    )
                krw = round_upbit_krw_notional(Decimal(str(krw_raw)))
                validate_upbit_notional(
                    side=side_code,
                    order_type=order_type,
                    quantity=qty,
                    price=krw,
                    market_krw_amount=krw,
                )
                return cls._with_identifier(
                    {
                        "market": market,
                        "side": side,
                        "ord_type": "price",
                        "price": str(krw),
                    },
                    request.client_order_id,
                    upbit_identifier=getattr(
                        request, "upbit_client_identifier", None
                    ),
                )
            # 시장가 매도: ord_type=market, volume만
            if qty <= 0:
                raise ValueError(
                    "Upbit market SELL requires volume"
                )
            validate_upbit_notional(
                side=side_code,
                order_type=order_type,
                quantity=qty,
                price=None,
            )
            return cls._with_identifier(
                {
                    "market": market,
                    "side": side,
                    "ord_type": "market",
                    "volume": str(qty),
                },
                request.client_order_id,
                upbit_identifier=getattr(
                    request, "upbit_client_identifier", None
                ),
            )

        # 지정가 — unit price + volume
        price = (
            None
            if request.price is None
            else round_upbit_price(Decimal(str(request.price)))
        )
        validate_upbit_notional(
            side=side_code,
            order_type=order_type,
            quantity=qty,
            price=price,
        )
        if price is None or price <= 0:
            raise ValueError("Upbit limit order requires price")
        if qty <= 0:
            raise ValueError("Upbit limit order requires volume")
        return cls._with_identifier(
            {
                "market": market,
                "side": side,
                "ord_type": "limit",
                "volume": str(qty),
                "price": str(price),
            },
            request.client_order_id,
            upbit_identifier=getattr(
                request, "upbit_client_identifier", None
            ),
        )

    @staticmethod
    def _with_identifier(
        body: dict[str, Any],
        client_order_id: str | None,
        *,
        upbit_identifier: str | None = None,
    ) -> dict[str, Any]:
        # Upbit identifier 우선 (최대 36자, 계정 Unique·재사용 불가)
        client_id = (
            (upbit_identifier or "").strip()
            or (client_order_id or "").strip()
        )
        if client_id:
            body["identifier"] = client_id[:36]
        return body

    @staticmethod
    def _side(side: BrokerOrderSide | str) -> str:
        value = side.value if isinstance(side, BrokerOrderSide) else str(side)
        if value.upper() == "BUY":
            return "bid"
        if value.upper() == "SELL":
            return "ask"
        raise ValueError(f"Unsupported side: {side}")
