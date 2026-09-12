"""KIWOOM ka10081 trade_value 단위 정규화 및 backfill idempotency 테스트."""

from datetime import date
from decimal import Decimal

from stock_platform.collectors.kiwoom.parser import KiwoomDailyParser
from stock_platform.collectors.kiwoom.trade_value_normalization import (
    KIWOOM_TRADE_VALUE_MILLION_KRW,
    kiwoom_trade_value_needs_million_won_backfill,
    normalize_kiwoom_trade_value_to_krw,
)
from stock_platform.collectors.upbit.parser import UpbitDailyParser


def test_normalize_kiwoom_trade_value_million_won_to_krw() -> None:
    """공식 백만원 단위 raw → canonical KRW."""

    raw = Decimal("52877")
    normalized = normalize_kiwoom_trade_value_to_krw(raw)
    assert normalized == Decimal("52877000000")


def test_parser_000270_fixture_trade_value_scale() -> None:
    """000270 기아 대표 표본 — close/volume/other 필드 multiplier 없음."""

    parser = KiwoomDailyParser()
    result = parser.parse(
        {
            "stk_dt_pole_chart_qry": [
                {
                    "dt": "20260818",
                    "cur_prc": "131700",
                    "open_pric": "130000",
                    "high_pric": "132000",
                    "low_pric": "129500",
                    "trde_qty": "401515",
                    "trde_prica": "52877",
                    "flu_rt": "0.50",
                }
            ]
        }
    )
    row = result[0]
    assert row.trade_date == date(2026, 8, 18)
    assert row.close_price == Decimal("131700")
    assert row.volume == Decimal("401515")
    assert row.trade_value == Decimal("52877000000")

    approx_notional = row.close_price * row.volume
    ratio = row.trade_value / approx_notional
    assert Decimal("0.01") < ratio < Decimal("100")


def test_parser_no_double_normalization_on_reparse() -> None:
    """parser는 raw 입력만 ×1e6 — 이미 원 단위 raw면 1e12로 커지지 않음."""

    parser = KiwoomDailyParser()
    raw_million = parser.parse(
        {
            "stk_dt_pole_chart_qry": [
                {
                    "dt": "20260818",
                    "cur_prc": "1000",
                    "open_pric": "990",
                    "high_pric": "1010",
                    "low_pric": "980",
                    "trde_qty": "1000",
                    "trde_prica": "1",
                }
            ]
        }
    )[0]
    assert raw_million.trade_value == KIWOOM_TRADE_VALUE_MILLION_KRW


def test_backfill_detection_idempotent_after_normalize() -> None:
    """정규화된 KRW 값은 backfill 대상이 아님."""

    close = Decimal("131700")
    volume = Decimal("401515")
    normalized = Decimal("52877000000")
    assert not kiwoom_trade_value_needs_million_won_backfill(
        trade_value=normalized,
        close_price=close,
        volume=volume,
    )
    assert kiwoom_trade_value_needs_million_won_backfill(
        trade_value=Decimal("52877"),
        close_price=close,
        volume=volume,
    )


def test_parse_official_style_daily_rows() -> None:
    parser = KiwoomDailyParser()

    # trde_prica=1046400 → 1,046,400 백만원 = 1.0464e12 KRW
    response = {
        "stk_dt_pole_chart_qry": [
            {
                "dt": "20260710",
                "cur_prc": "+87200",
                "open_pric": "86000",
                "high_pric": "+87500",
                "low_pric": "-85500",
                "trde_qty": "12,000,000",
                "trde_prica": "1046400",
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
    assert row.trade_value == Decimal("1046400000000")
    assert row.change_rate == Decimal("1.28")


def test_upbit_trade_value_unchanged_krw() -> None:
    """Upbit candle_acc_trade_price는 이미 KRW — parser 변경 영향 없음."""

    parser = UpbitDailyParser()
    row = parser.parse(
        [
            {
                "candle_date_time_kst": "2026-08-18T09:00:00",
                "opening_price": 100,
                "high_price": 110,
                "low_price": 90,
                "trade_price": 105,
                "candle_acc_trade_volume": 1000,
                "candle_acc_trade_price": 105000,
            }
        ]
    )[0]
    assert row.trade_value == Decimal("105000")
