from decimal import Decimal

from stock_platform.broker.kiwoom.cancel_replace_mapper import (
    KiwoomCancelReplaceMapper,
)
from stock_platform.broker.kiwoom.cancel_replace_models import (
    KiwoomCancelOrderRequest,
    KiwoomReplaceOrderRequest,
)


def test_cancel_mapping():
    body = KiwoomCancelReplaceMapper.cancel_body(
        KiwoomCancelOrderRequest(
            broker_order_id="100",
            exchange_code="KRX",
            symbol="005930",
            cancel_quantity=Decimal("3"),
        )
    )

    assert body == {
        "dmst_stex_tp": "KRX",
        "orig_ord_no": "100",
        "stk_cd": "005930",
        "cncl_qty": "3",
    }


def test_replace_mapping():
    body = KiwoomCancelReplaceMapper.replace_body(
        KiwoomReplaceOrderRequest(
            broker_order_id="100",
            exchange_code="KRX",
            symbol="005930",
            replace_quantity=Decimal("2"),
            replace_price=Decimal("71000"),
        )
    )

    assert body["orig_ord_no"] == "100"
    assert body["mdfy_qty"] == "2"
    assert body["mdfy_uv"] == "71000"
