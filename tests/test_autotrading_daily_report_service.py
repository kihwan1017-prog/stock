"""Tests — autotrading daily operation report (READ ONLY)."""

from __future__ import annotations

from datetime import date

from stock_platform.operation.autotrading_daily_report_service import (
    _HEALTH_LABEL,
    _fmt_krw_signed,
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


def test_why_no_trade_ko_kiwoom_closed_not_system_check() -> None:
    msgs = _why_no_trade_ko(
        broker="KIWOOM",
        ops={
            "krx_session_phase": "CLOSED",
            "live": "OFF",
            "market_feed": {"status": "DISCONNECTED"},
            "reliability": {
                "no_trade_classification": "SYSTEM_FAILURE",
                "kiwoom_funnel": {"FIRST_ZERO_STAGE": "MARKET_CLOSED"},
            },
        },
        funnel_first_zero="NO_GOLDEN_CROSS_SIGNAL",
        funnel_reason=None,
    )
    assert any("정규장" in m or "휴장" in m or "주말" in m for m in msgs)
    assert not any("시스템 점검" in m for m in msgs)


def test_telegram_dedupe_key() -> None:
    assert telegram_dedupe_key(date(2026, 8, 28)) == "DAILY_TRADING_REPORT:2026-08-28"


def test_format_daily_report_telegram_v2_canonical_keys() -> None:
    body = format_daily_report_telegram(
        {
            "report_date": "2026-09-05",
            "generated_at": "2026-09-05T14:30:00+00:00",
            "upbit": {
                "health_label": _HEALTH_LABEL["GREEN"],
                "auto_trading_state": "RUNNING",
                "trading_summary": {
                    "buy_order_count": 103,
                    "sell_order_count": 101,
                    "buy_filled_count": 100,
                    "sell_filled_count": 98,
                    "closed_round_trips": 97,
                    "wins": 24,
                    "losses": 73,
                    "win_rate_pct": "24.7",
                    "gross_pnl": 1434.06,
                    "fees": 1034.33,
                    "realized_pnl": 399.73,
                    "profit_factor": "1.54",
                    "open_position_count": 3,
                    "open_order_count": 0,
                },
                "exit_reason_performance": [
                    {
                        "exit_reason_label_ko": "MA 데드크로스",
                        "closed_trade_count": 40,
                        "net_pnl": 100,
                    }
                ],
                "top_winners": [{"symbol": "AAA", "net_pnl": 50}],
                "top_losers": [{"symbol": "BBB", "net_pnl": -20}],
                "why_no_trade": [],
            },
            "kiwoom": {
                "health_label": _HEALTH_LABEL["YELLOW"],
                "auto_trading_state": "WAITING",
                "trading_summary": {
                    "buy_filled_count": 0,
                    "sell_filled_count": 0,
                    "closed_round_trips": 0,
                    "wins": 0,
                    "losses": 0,
                    "gross_pnl": 0,
                    "fees": 0,
                    "realized_pnl": 0,
                    "open_position_count": 0,
                },
                "why_no_trade": ["현재 정규장이 종료되었습니다."],
            },
            "incidents": {
                "today_count": 2,
                "today_incident_count": 2,
                "resolved_today_count": 1,
                "open_count": 3,
                "active_unresolved_incident_count": 3,
            },
        }
    )
    assert "[시스템] 자동매매 일일보고" in body
    assert "2026-09-05" in body
    assert "완료 거래: 97건" in body
    assert "매매손익(Gross): +1,434원" in body or "매매손익(Gross): +1,434" in body
    assert "순손익(Net): +400원" in body or "순손익(Net): +399.73" in body or "+400" in body
    assert "실현손익: 0" not in body.split("[업비트]")[1].split("[키움]")[0]
    assert "시스템 장애(당일): 2건" in body
    assert "현재 미복구 장애: 3건" in body
    assert "미거래 이유" in body or "정규장" in body


def test_fmt_krw_signed() -> None:
    assert _fmt_krw_signed(399.73).startswith("+")
    assert "399" in _fmt_krw_signed(399.73) or "400" in _fmt_krw_signed(399.73)


def test_health_labels_no_trade_not_error() -> None:
    from stock_platform.operation.autotrading_daily_report_service import _health_class

    code, label = _health_class(
        broker="KIWOOM",
        ops={
            "krx_session_phase": "CLOSED",
            "live": "OFF",
            "market_feed": {"status": "DISCONNECTED"},
            "reliability": {"kiwoom_funnel": {"FIRST_ZERO_STAGE": "MARKET_CLOSED"}},
        },
        order_stats={},
    )
    assert code == "YELLOW"
    assert label == _HEALTH_LABEL["YELLOW"]
    assert "대기" in _HEALTH_LABEL["YELLOW"]
