from decimal import Decimal

from stock_platform.broker.kiwoom.account_mapper import (
    KiwoomAccountMapper,
)


def test_maps_account_and_positions() -> None:
    result = KiwoomAccountMapper.map(
        account_number="1234567890",
        deposit_payload={
            "entr": "10,000,000",
            "ord_alow_amt": "8,000,000",
        },
        balance_payload={
            "tot_pur_amt": "2,000,000",
            "tot_evlt_amt": "2,200,000",
            "tot_evlt_pl": "200,000",
            "tot_prft_rt": "10.0",
            "acnt_evlt_remn_indv_tot": [
                {
                    "stk_cd": "A005930",
                    "stk_nm": "삼성전자",
                    "rmnd_qty": "10",
                    "trde_able_qty": "8",
                    "pur_pric": "70000",
                    "cur_prc": "72000",
                    "pur_amt": "700000",
                    "evlt_amt": "720000",
                    "evltv_prft": "20000",
                    "prft_rt": "2.8571",
                }
            ],
        },
    )

    assert result.deposit_amount == Decimal(
        "10000000"
    )
    assert result.available_order_amount == Decimal(
        "8000000"
    )
    assert len(result.positions) == 1
    assert result.positions[0].symbol == "005930"
    assert result.positions[0].quantity == Decimal("10")
