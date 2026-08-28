"""Tests — autotrading daily operation report (READ ONLY)."""

from __future__ import annotations

from datetime import date

from stock_platform.operation.autotrading_daily_report_service import (
    _HEALTH_LABEL,
    _kst_day_bounds,
    _why_no_trade_ko,
    format_daily_report_telegram,
    telegram_dedupe_key,
)


def test_kst_day_bounds() -> None:
    start, end = _kst_day_bounds(date(2026, 8, 28))
    assert start.tzinfo is not None
    assert end > start
    assert (end - start).total_seconds() == 86400


def test_why_no_trade_ko_normal_no_signal() -> None:
    msgs = _why_no_trade_ko(
        broker="UPBIT",
        ops={"reliability": {"no_trade_classification": "NORMAL_NO_SIGNAL"}},
        funnel_first_zero=None,
        funnel_reason=None,
    )
    assert any("매수 조건" in m for m in msgs)


def test_why_no_trade_ko_kiwoom_closed() -> None:
    msgs = _why_no_trade_ko(
        broker="KIWOOM",
        ops={"krx_session_phase": "CLOSED", "market_feed": {"status": "REAL_FRESH"}},
        funnel_first_zero="NO_GOLDEN_CROSS_SIGNAL",
        funnel_reason=None,
    )
    assert any("Golden Cross" in m or "종료" in m for m in msgs)


def test_telegram_dedupe_key() -> None:
    assert telegram_dedupe_key(date(2026, 8, 28)) == "DAILY_TRADING_REPORT:2026-08-28"


def test_format_daily_report_telegram() -> None:
    body = format_daily_report_telegram(
        {
            "report_date": "2026-08-28",
            "upbit": {
                "health_label": _HEALTH_LABEL["YELLOW"],
                "trading_summary": {
                    "buy_order_count": 1,
                    "sell_order_count": 0,
                    "realized_pnl": 1000,
                    "open_position_count": 2,
                },
                "why_no_trade": ["신호 대기"],
            },
            "kiwoom": {
                "health_label": _HEALTH_LABEL["GREEN"],
                "trading_summary": {
                    "buy_order_count": 0,
                    "sell_order_count": 0,
                    "realized_pnl": 0,
                    "open_position_count": 0,
                },
                "why_no_trade": ["장 마감"],
            },
            "incidents": {"today_count": 0, "open_count": 0},
        }
    )
    assert "[시스템] 자동매매 일일보고" in body
    assert "2026-08-28" in body
    assert "[업비트]" in body
    assert "[키움]" in body


def test_health_labels_no_trade_not_error() -> None:
    assert "대기" in _HEALTH_LABEL["YELLOW"]
