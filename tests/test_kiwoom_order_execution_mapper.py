from decimal import Decimal

from stock_platform.broker.kiwoom.ws_mapper import (
    KiwoomOrderExecutionMapper,
)
from stock_platform.broker.kiwoom.ws_models import (
    KiwoomOrderEventType,
)


def test_maps_partial_fill_event() -> None:
    event = KiwoomOrderExecutionMapper.map(
        {
            "data": {
                "acnt_no": "1234567890",
                "ord_no": "10001",
                "stk_cd": "A005930",
                "io_tp_nm": "매수",
                "ord_qty": "10",
                "cntr_qty": "4",
                "oso_qty": "6",
                "cntr_prc": "70000",
                "ord_stt": "체결",
                "cntr_tm": "101530",
            }
        }
    )

    assert event.symbol == "005930"
    assert event.filled_quantity == Decimal("4")
    assert event.remaining_quantity == Decimal("6")
    assert event.event_type == (
        KiwoomOrderEventType.PARTIALLY_FILLED
    )
