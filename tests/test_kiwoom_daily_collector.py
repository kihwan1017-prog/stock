from datetime import date

import pytest

from stock_platform.brokers.kiwoom.client import KiwoomResponse
from stock_platform.collectors.kiwoom.daily_collector import (
    KiwoomDailyCollector,
)


class FakeKiwoomClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def request(self, **kwargs) -> KiwoomResponse:
        self.calls.append(kwargs)

        if len(self.calls) == 1:
            return KiwoomResponse(
                body={
                    "stk_dt_pole_chart_qry": [
                        {
                            "dt": "20260710",
                            "cur_prc": "87200",
                            "open_pric": "86000",
                            "high_pric": "87500",
                            "low_pric": "85500",
                            "trde_qty": "120",
                        },
                        {
                            "dt": "20260709",
                            "cur_prc": "85000",
                            "open_pric": "84500",
                            "high_pric": "85500",
                            "low_pric": "84000",
                            "trde_qty": "100",
                        },
                    ]
                },
                api_id="ka10081",
                has_more=True,
                next_key="page-2",
            )

        return KiwoomResponse(
            body={
                "stk_dt_pole_chart_qry": [
                    {
                        "dt": "20260708",
                        "cur_prc": "84000",
                        "open_pric": "83000",
                        "high_pric": "84500",
                        "low_pric": "82500",
                        "trde_qty": "90",
                    },
                    {
                        "dt": "20260707",
                        "cur_prc": "83000",
                        "open_pric": "82000",
                        "high_pric": "83500",
                        "low_pric": "81500",
                        "trde_qty": "80",
                    },
                ]
            },
            api_id="ka10081",
            has_more=False,
            next_key=None,
        )


@pytest.mark.asyncio
async def test_collect_paginates_filters_and_sorts() -> None:
    client = FakeKiwoomClient()
    collector = KiwoomDailyCollector(client)  # type: ignore[arg-type]

    result = await collector.collect(
        symbol="005930",
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
    )

    assert [row.trade_date for row in result] == [
        date(2026, 7, 8),
        date(2026, 7, 9),
        date(2026, 7, 10),
    ]
    assert len(client.calls) == 2
    assert client.calls[0]["api_id"] == "ka10081"
    assert client.calls[0]["endpoint"] == "/api/dostk/chart"
    assert client.calls[0]["body"] == {
        "stk_cd": "005930",
        "base_dt": "20260710",
        "upd_stkpc_tp": "1",
    }
    assert client.calls[1]["continue_yn"] == "Y"
    assert client.calls[1]["next_key"] == "page-2"
