from decimal import Decimal

from stock_platform.broker.kiwoom.execution_parser import (
    KiwoomExecutionParser,
)


def test_parse_named_fields():
    events = KiwoomExecutionParser().parse_message(
        {
            "type": "00",
            "data": [
                {
                    "ord_no": "100",
                    "cntr_no": "200",
                    "stk_cd": "A005930",
                    "cntr_pric": "70,000",
                    "cntr_qty": "2",
                    "oso_qty": "3",
                    "cntr_tm": "101530",
                }
            ],
        }
    )

    assert len(events) == 1
    event = events[0]
    assert event.broker_order_id == "100"
    assert event.broker_execution_id == "200"
    assert event.symbol == "005930"
    assert event.execution_price == Decimal(
        "70000"
    )
    assert event.execution_quantity == Decimal(
        "2"
    )
    assert event.remaining_quantity == Decimal(
        "3"
    )


def test_parse_fid_values():
    events = KiwoomExecutionParser().parse_message(
        {
            "trnm": "REAL",
            "data": [
                {
                    "values": {
                        "9203": "100",
                        "909": "200",
                        "9001": "A005930",
                        "910": "+70000",
                        "911": "2",
                        "902": "0",
                    }
                }
            ],
        }
    )

    assert len(events) == 1
    assert events[0].remaining_quantity == 0
