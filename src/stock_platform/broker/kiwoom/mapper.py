from datetime import datetime, timezone
from decimal import Decimal
from stock_platform.broker.models import (
    BrokerOrderRequest, BrokerOrderResponse, BrokerOrderStatus, BrokerOrderType,
)

class KiwoomOrderMapper:
    @staticmethod
    def to_body(request: BrokerOrderRequest, market_trade_type: str, limit_trade_type: str) -> dict[str, str]:
        if request.quantity <= 0:
            raise ValueError("quantity must be greater than zero")
        if request.order_type == BrokerOrderType.LIMIT and request.price is None:
            raise ValueError("price is required for LIMIT order")
        return {
            "dmst_stex_tp": "KRX",
            "stk_cd": request.symbol,
            "ord_qty": str(request.quantity.quantize(Decimal("1"))),
            "ord_uv": "" if request.order_type == BrokerOrderType.MARKET else str(request.price),
            "trde_tp": market_trade_type if request.order_type == BrokerOrderType.MARKET else limit_trade_type,
            "cond_uv": "",
        }

    @staticmethod
    def to_response(request: BrokerOrderRequest, data: dict) -> BrokerOrderResponse:
        now = datetime.now(timezone.utc)
        order_no = str(data.get("ord_no") or data.get("order_no") or "").strip()
        if not order_no:
            raise ValueError("Kiwoom order response has no order number")
        return BrokerOrderResponse(
            broker_order_id=order_no, client_order_id=request.client_order_id,
            status=BrokerOrderStatus.ACCEPTED, accepted_quantity=request.quantity,
            filled_quantity=Decimal("0"), average_fill_price=None,
            message=data.get("return_msg"), requested_at=now, updated_at=now,
        )
