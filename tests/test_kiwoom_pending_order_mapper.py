from decimal import Decimal
from stock_platform.broker.kiwoom.pending_mapper import KiwoomPendingOrderMapper
from stock_platform.broker.pending_models import PendingOrderStatus

def test_maps_partial_fill():
    rows = KiwoomPendingOrderMapper.map_list("123", {"oso":[{
        "ord_no":"1234567","stk_cd":"A005930","stk_nm":"삼성전자",
        "io_tp_nm":"매수","ord_qty":"10","cntr_qty":"4",
        "oso_qty":"6","ord_uv":"70000"
    }]})
    assert rows[0].symbol == "005930"
    assert rows[0].filled_quantity == Decimal("4")
    assert rows[0].remaining_quantity == Decimal("6")
    assert rows[0].status == PendingOrderStatus.PARTIALLY_FILLED
