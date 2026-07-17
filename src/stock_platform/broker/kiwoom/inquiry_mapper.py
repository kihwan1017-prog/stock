from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from stock_platform.broker.kiwoom.inquiry_models import (
    KiwoomExecution,
    KiwoomPendingOrder,
)


def _decimal(
    value: Any,
    default: str = "0",
) -> Decimal:
    text = str(
        default if value in (None, "") else value
    ).replace(",", "").strip()

    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal(default)


class KiwoomInquiryMapper:
    @staticmethod
    def pending_order(
        item: dict[str, Any],
    ) -> KiwoomPendingOrder:
        order_qty = _decimal(
            item.get("ord_qty")
            or item.get("order_qty")
        )
        filled_qty = _decimal(
            item.get("cntr_qty")
            or item.get("filled_qty")
        )
        remaining_qty = _decimal(
            item.get("oso_qty")
            or item.get("remaining_qty"),
            str(max(order_qty - filled_qty, Decimal("0"))),
        )

        price_value = (
            item.get("ord_pric")
            or item.get("ord_uv")
            or item.get("order_price")
        )

        return KiwoomPendingOrder(
            broker_order_id=str(
                item.get("ord_no")
                or item.get("broker_order_id")
                or ""
            ),
            symbol=str(
                item.get("stk_cd")
                or item.get("symbol")
                or ""
            ),
            side_code=(
                item.get("io_tp_nm")
                or item.get("side_code")
            ),
            order_quantity=order_qty,
            filled_quantity=filled_qty,
            remaining_quantity=remaining_qty,
            order_price=(
                None
                if price_value in (None, "")
                else _decimal(price_value)
            ),
            raw_payload=item,
        )

    @staticmethod
    def execution(
        item: dict[str, Any],
    ) -> KiwoomExecution:
        return KiwoomExecution(
            broker_order_id=str(
                item.get("ord_no")
                or item.get("broker_order_id")
                or ""
            ),
            symbol=str(
                item.get("stk_cd")
                or item.get("symbol")
                or ""
            ),
            execution_number=(
                item.get("cntr_no")
                or item.get("execution_number")
            ),
            execution_quantity=_decimal(
                item.get("cntr_qty")
                or item.get("execution_quantity")
            ),
            execution_price=_decimal(
                item.get("cntr_pric")
                or item.get("execution_price")
            ),
            raw_payload=item,
        )
