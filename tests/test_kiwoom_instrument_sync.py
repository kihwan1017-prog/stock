"""KIWOOM ka10099 instrument collector / sync targeted tests.

실 broker CREATE 금지. 공식 샘플 필드만 사용.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from stock_platform.broker.kiwoom.market.client import KiwoomResponse
from stock_platform.collectors.kiwoom.instrument_collector import (
    KiwoomInstrumentCollector,
    parse_instrument_rows,
)
from stock_platform.collectors.kiwoom.instrument_sync_service import (
    KiwoomInstrumentSyncService,
)
from stock_platform.collectors.kiwoom.parser import (
    KiwoomDailyParseError,
    KiwoomDailyParser,
)


def test_parse_instrument_official_fields_and_classification() -> None:
    body = {
        "return_code": 0,
        "list": [
            {
                "code": "005930",
                "name": "삼성전자",
                "listCount": "5900000000",
                "auditInfo": "",
                "regDay": "19750611",
                "lastPrice": "87000",
                "state": "정상",
                "marketCode": "STK",
                "marketName": "코스피",
                "upName": "전기전자",
                "upSizeName": "대형",
                "orderWarning": "0",
                "companyClassName": "",
                "nxtEnable": "1",
            }
        ],
    }
    rows = parse_instrument_rows(body, mrkt_tp="0")
    assert len(rows) == 1
    row = rows[0]
    assert row.symbol == "005930"
    assert row.name == "삼성전자"
    assert row.exchange_code == "KRX"
    assert row.asset_type == "STOCK"
    assert row.is_active is True
    assert row.market_segment == "KOSPI"
    assert row.listed_date == date(1975, 6, 11)
    assert row.extra_data["mrkt_tp"] == "0"


def test_parse_strips_mock_prefix_and_skips_duplicate() -> None:
    body = {
        "list": [
            {"code": "A005930", "name": "삼성전자", "state": "정상"},
            {"code": "005930", "name": "삼성전자", "state": "정상"},
        ]
    }
    rows = parse_instrument_rows(body, mrkt_tp="0")
    assert [item.symbol for item in rows] == ["005930"]


def test_parse_etf_etn_and_halted_status() -> None:
    etf = parse_instrument_rows(
        {"list": [{"code": "069500", "name": "KODEX 200", "state": "정상"}]},
        mrkt_tp="8",
    )[0]
    etn = parse_instrument_rows(
        {"list": [{"code": "520021", "name": "ETN샘플", "state": "정상"}]},
        mrkt_tp="60",
    )[0]
    halted = parse_instrument_rows(
        {"list": [{"code": "000001", "name": "정지종목", "state": "거래정지"}]},
        mrkt_tp="10",
    )[0]
    assert etf.asset_type == "ETF" and etf.is_etf is True
    assert etn.is_etn is True and etn.asset_type == "ETF"
    assert halted.market_segment == "KOSDAQ"
    assert halted.is_active is False


@pytest.mark.asyncio
async def test_undocumented_market_type_rejected() -> None:
    collector = KiwoomInstrumentCollector(client=SimpleNamespace())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="undocumented mrkt_tp"):
        await collector.collect(market_types=("999",))


class FakeInstrumentClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return KiwoomResponse(
                body={
                    "list": [
                        {"code": "005930", "name": "삼성전자", "state": "정상"},
                    ]
                },
                api_id="ka10099",
                has_more=True,
                next_key="page-2",
            )
        return KiwoomResponse(
            body={
                "list": [
                    {"code": "000660", "name": "SK하이닉스", "state": "정상"},
                ]
            },
            api_id="ka10099",
            has_more=False,
            next_key=None,
        )


@pytest.mark.asyncio
async def test_collector_paginates_continuation() -> None:
    client = FakeInstrumentClient()
    collector = KiwoomInstrumentCollector(client, page_delay_seconds=0)  # type: ignore[arg-type]
    rows = await collector.collect(market_types=("0",), max_pages=10)
    assert [item.symbol for item in rows] == ["005930", "000660"]
    assert len(client.calls) == 2
    assert client.calls[0]["api_id"] == "ka10099"
    assert client.calls[0]["endpoint"] == "/api/dostk/stkinfo"
    assert client.calls[0]["body"] == {"mrkt_tp": "0"}
    assert client.calls[1]["continue_yn"] == "Y"
    assert client.calls[1]["next_key"] == "page-2"


class FakeInstrumentService:
    def __init__(self) -> None:
        self.existing: dict[str, SimpleNamespace] = {}
        self.upserts: list[list[dict]] = []

    def list(self, **kwargs):
        return list(self.existing.values())

    def upsert_many(self, rows):
        self.upserts.append(rows)
        for row in rows:
            self.existing[row["symbol"]] = SimpleNamespace(**row)
        return len(rows)


@pytest.mark.asyncio
async def test_instrument_sync_idempotent_insert_then_update() -> None:
    client = FakeInstrumentClient()
    collector = KiwoomInstrumentCollector(client, page_delay_seconds=0)  # type: ignore[arg-type]
    service = FakeInstrumentService()
    sync = KiwoomInstrumentSyncService(collector, service)  # type: ignore[arg-type]

    first = await sync.sync(market_types=("0",), max_pages=10)
    assert first.inserted == 2
    assert first.updated == 0
    assert first.failed == 0
    assert first.kospi == 2

    client.calls.clear()
    second = await sync.sync(market_types=("0",), max_pages=10)
    assert second.inserted == 0
    assert second.updated == 2
    assert len(service.upserts) == 2


def test_daily_parser_rejects_bad_ohlc_quality() -> None:
    parser = KiwoomDailyParser()
    with pytest.raises(KiwoomDailyParseError):
        parser.parse(
            {
                "stk_dt_pole_chart_qry": [
                    {
                        "dt": "20260710",
                        "cur_prc": "80000",
                        "open_pric": "90000",
                        "high_pric": "85000",
                        "low_pric": "84000",
                        "trde_qty": "10",
                    }
                ]
            }
        )
    with pytest.raises(KiwoomDailyParseError):
        parser.parse(
            {
                "stk_dt_pole_chart_qry": [
                    {
                        "dt": "20260710",
                        "cur_prc": "0",
                        "open_pric": "0",
                        "high_pric": "0",
                        "low_pric": "0",
                        "trde_qty": "0",
                    }
                ]
            }
        )
