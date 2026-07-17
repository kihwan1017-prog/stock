from __future__ import annotations

from stock_platform.broker.kiwoom.cancel_replace_models import (
    KiwoomCancelOrderRequest,
    KiwoomReplaceOrderRequest,
)


class KiwoomCancelReplaceMapper:
    REPLACE_API_ID = "kt10002"
    CANCEL_API_ID = "kt10003"

    @staticmethod
    def replace_body(
        request: KiwoomReplaceOrderRequest,
    ) -> dict[str, str]:
        if request.replace_quantity <= 0:
            raise ValueError(
                "replace_quantity must be positive"
            )
        if request.replace_price <= 0:
            raise ValueError(
                "replace_price must be positive"
            )

        return {
            "dmst_stex_tp": request.exchange_code.upper(),
            "orig_ord_no": request.broker_order_id,
            "stk_cd": request.symbol,
            "mdfy_qty": str(int(request.replace_quantity)),
            "mdfy_uv": str(int(request.replace_price)),
        }

    @staticmethod
    def cancel_body(
        request: KiwoomCancelOrderRequest,
    ) -> dict[str, str]:
        if request.cancel_quantity <= 0:
            raise ValueError(
                "cancel_quantity must be positive"
            )

        return {
            "dmst_stex_tp": request.exchange_code.upper(),
            "orig_ord_no": request.broker_order_id,
            "stk_cd": request.symbol,
            "cncl_qty": str(int(request.cancel_quantity)),
        }
