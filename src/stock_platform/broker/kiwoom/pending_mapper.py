from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from stock_platform.broker.pending_models import PendingOrderSnapshot, PendingOrderStatus

ZERO = Decimal("0")

class KiwoomPendingOrderMapper:
    LIST_KEYS = ("oso", "unexecuted", "pending_orders", "orders", "items")

    @classmethod
    def map_list(cls, account_number: str, payload: dict[str, Any]) -> list[PendingOrderSnapshot]:
        now = datetime.now(timezone.utc)
        return [cls._one(account_number, row, now) for row in cls._rows(payload)
                if cls._text(row, "ord_no", "order_no")]

    @classmethod
    def _one(cls, account_number: str, row: dict[str, Any],
             now: datetime) -> PendingOrderSnapshot:
        ordered = cls._num(row, "ord_qty", "order_quantity")
        filled = cls._num(row, "cntr_qty", "filled_quantity", "executed_quantity")
        remaining = cls._num(row, "oso_qty", "remaining_quantity", "unfilled_quantity")
        if remaining == ZERO and ordered >= filled:
            remaining = ordered - filled
        raw_status = cls._text(row, "ord_stt", "status")
        status = PendingOrderStatus.ACCEPTED
        if "취소" in raw_status or "CANCEL" in raw_status.upper():
            status = PendingOrderStatus.CANCELLED
        elif "거부" in raw_status or "REJECT" in raw_status.upper():
            status = PendingOrderStatus.REJECTED
        elif remaining == ZERO and filled > ZERO:
            status = PendingOrderStatus.FILLED
        elif filled > ZERO and remaining > ZERO:
            status = PendingOrderStatus.PARTIALLY_FILLED

        side_raw = cls._text(row, "io_tp_nm", "ord_tp_nm", "side")
        side = "BUY" if ("매수" in side_raw or "BUY" in side_raw.upper()) else (
            "SELL" if ("매도" in side_raw or "SELL" in side_raw.upper()) else "UNKNOWN"
        )

        return PendingOrderSnapshot(
            broker_code="KIWOOM", account_number=account_number,
            broker_order_id=cls._text(row, "ord_no", "order_no"),
            exchange_code=cls._text(row, "dmst_stex_tp", "exchange_code", default="KRX"),
            symbol=cls._text(row, "stk_cd", "symbol").lstrip("A"),
            name=cls._text(row, "stk_nm", "name"),
            side=side, order_type=cls._text(row, "trde_tp", "order_type", default="UNKNOWN"),
            order_quantity=ordered, order_price=cls._opt_num(row, "ord_uv", "order_price"),
            filled_quantity=filled, remaining_quantity=remaining,
            average_fill_price=cls._opt_num(row, "avg_cntr_prc", "average_fill_price"),
            status=status, ordered_at=None, synchronized_at=now, raw_data=row,
        )

    @classmethod
    def _rows(cls, payload):
        for key in cls.LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        return []

    @staticmethod
    def _text(payload, *keys, default=""):
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return str(value).strip()
        return default

    @staticmethod
    def _opt_num(payload, *keys):
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                try:
                    return Decimal(str(value).replace(",", "").strip())
                except InvalidOperation:
                    pass
        return None

    @classmethod
    def _num(cls, payload, *keys):
        value = cls._opt_num(payload, *keys)
        return value if value is not None else ZERO
