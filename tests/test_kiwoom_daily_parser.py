from datetime import date
from decimal import Decimal

from stock_platform.collectors.kiwoom.parser import KiwoomDailyParser


def test_parse_official_style_daily_rows() -> None:
    parser = KiwoomDailyParser()

    response = {
        "stk_dt_pole_chart_qry": [
            {
                "dt": "20260710",
                "cur_prc": "+87200",
                "open_pric": "86000",
                "high_pric": "+87500",
                "low_pric": "-85500",
                "trde_qty": "12,000,000",
                "trde_prica": "1046400000000",
                "flu_rt": "1.28",
            }
        ]
    }

    result = parser.parse(response)

    assert len(result) == 1
    row = result[0]
    assert row.trade_date == date(2026, 7, 10)
    assert row.open_price == Decimal("86000")
    assert row.high_price == Decimal("87500")
    assert row.low_price == Decimal("85500")
    assert row.close_price == Decimal("87200")
    assert row.volume == Decimal("12000000")
    assert row.change_rate == Decimal("1.28")


def test_parse_discovers_nested_daily_list() -> None:
    parser = KiwoomDailyParser()

    response = {
        "result": {
            "items": [
                {
                    "dt": "20260709",
                    "cur_prc": "85000",
                    "open_pric": "84000",
                    "high_pric": "85500",
                    "low_pric": "83500",
                    "trde_qty": "100",
                }
            ]
        }
    }

    result = parser.parse(response)

    assert result[0].trade_date == date(2026, 7, 9)
    assert result[0].trade_value == Decimal("0")
