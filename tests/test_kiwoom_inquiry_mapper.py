from decimal import Decimal

from stock_platform.broker.kiwoom.inquiry_mapper import (
    KiwoomInquiryMapper,
)


def test_pending_order_mapping():
    result = KiwoomInquiryMapper.pending_order(
        {
            "ord_no": "100",
            "stk_cd": "005930",
            "ord_qty": "10",
            "cntr_qty": "3",
            "oso_qty": "7",
            "ord_pric": "70,000",
        }
    )

    assert result.broker_order_id == "100"
    assert result.order_quantity == Decimal("10")
    assert result.filled_quantity == Decimal("3")
    assert result.remaining_quantity == Decimal("7")


def test_execution_mapping():
    result = KiwoomInquiryMapper.execution(
        {
            "ord_no": "100",
            "stk_cd": "005930",
            "cntr_no": "1",
            "cntr_qty": "2",
            "cntr_pric": "69,900",
        }
    )

    assert result.execution_quantity == Decimal("2")
    assert result.execution_price == Decimal("69900")
