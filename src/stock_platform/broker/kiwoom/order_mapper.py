from decimal import Decimal
from stock_platform.broker.models import BrokerOrderRequest

class KiwoomOrderMapper:
    BUY_API_ID = "kt10000"
    SELL_API_ID = "kt10001"

    @classmethod
    def api_id(cls, side: str) -> str:
        side = side.upper()
        if side == "BUY":
            return cls.BUY_API_ID
        if side == "SELL":
            return cls.SELL_API_ID
        raise ValueError(f"Unsupported side: {side}")

    @staticmethod
    def trade_type(order_type: str, time_in_force: str) -> str:
        key = (order_type.upper(), time_in_force.upper())
        mapping = {
            ("LIMIT", "DAY"): "0",
            ("MARKET", "DAY"): "3",
            ("LIMIT", "IOC"): "10",
            ("MARKET", "IOC"): "13",
            ("LIMIT", "FOK"): "20",
            ("MARKET", "FOK"): "23",
        }
        if key not in mapping:
            raise ValueError(f"Unsupported Kiwoom order condition: {key}")
        return mapping[key]

    @classmethod
    def body(cls, request: BrokerOrderRequest) -> dict[str, str]:
        body = {
            "dmst_stex_tp": request.exchange_code.upper(),
            "stk_cd": request.symbol,
            "ord_qty": str(int(request.quantity)),
            "trde_tp": cls.trade_type(
                request.order_type,
                request.time_in_force,
            ),
        }
        if request.order_type.upper() == "LIMIT":
            if request.price is None or request.price <= Decimal("0"):
                raise ValueError("LIMIT order requires price > 0")
            body["ord_uv"] = str(int(request.price))
        return body
