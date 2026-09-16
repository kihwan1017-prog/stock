"""Telegram operational allowlist + market title prefix."""

from __future__ import annotations

from stock_platform.notification.telegram_policy import (
    TELEGRAM_OPERATIONAL_ALLOWLIST,
    ensure_market_title_prefix,
    evaluate_telegram_policy,
    is_telegram_event_allowlisted,
)


def test_allowlist_includes_core_ops() -> None:
    for et in (
        "SYSTEM_START",
        "ORDER_FILLED",
        "POSITION_CLOSED",
        "MONITORING_ALERT",
        "AI_GATE_RECOMMENDATION_CHANGED",
        "UPBIT_PORTFOLIO_SLOT_ASSIGNED",
        "UPBIT_SCANNER_CANDIDATE",
        "UPBIT_SCANNER_SHADOW_OPENED",
        "AUTOTRADING_DAILY_REPORT",
        "UPBIT_IMPORTANT_NOTICE",
        "KIWOOM_IMPORTANT_DISCLOSURE",
    ):
        assert is_telegram_event_allowlisted(et)


def test_daily_report_telegram_policy_allows() -> None:
    """23:30 Daily Report — allowlist + SYSTEM category, dedupe key 유지."""

    d = evaluate_telegram_policy(
        event_type="AUTOTRADING_DAILY_REPORT",
        detail={
            "report_date": "2026-08-28",
            "dedupe_key": "DAILY_TRADING_REPORT:2026-08-28",
        },
    )
    assert d.allowed is True
    assert d.reason != "EVENT_NOT_ALLOWLISTED"
    assert d.category == "SYSTEM"


def test_allowlist_excludes_noise() -> None:
    for et in (
        "ORDER_SUBMITTED",
        "ORDER_PARTIAL_FILLED",
        "REALIZED_PNL",
        "BACKTEST_COMPLETE",
        "RUNTIME_STARTED",
        "UPBIT_PORTFOLIO_CANDIDATE_REPLACED",
    ):
        assert not is_telegram_event_allowlisted(et)
        d = evaluate_telegram_policy(
            event_type=et, detail={"broker_code": "UPBIT"}
        )
        assert d.allowed is False
        assert d.reason == "EVENT_NOT_ALLOWLISTED"


def test_prefix_upbit_kiwoom_system() -> None:
    assert ensure_market_title_prefix("매수 체결", market="UPBIT").startswith(
        "[업비트]"
    )
    assert ensure_market_title_prefix("매도 체결", market="KIWOOM").startswith(
        "[키움]"
    )
    assert ensure_market_title_prefix("모니터링", market="COMMON").startswith(
        "[시스템]"
    )
    # 중복 prefix 방지
    assert (
        ensure_market_title_prefix("[업비트] 매수 체결", market="UPBIT")
        == "[업비트] 매수 체결"
    )
    # 영문/구표기 정규화
    assert ensure_market_title_prefix(
        "[UPBIT] 서버 시작", market="UPBIT"
    ).startswith("[업비트]")
    assert ensure_market_title_prefix(
        "[키움증권] 매수", market="KIWOOM"
    ).startswith("[키움]")


def test_allowlisted_trading_still_allowed() -> None:
    d = evaluate_telegram_policy(
        event_type="ORDER_FILLED",
        detail={"broker_code": "UPBIT", "symbol": "KRW-XRP"},
    )
    assert d.allowed is True
    assert d.market == "UPBIT"


def test_allowlist_frozen_set_non_empty() -> None:
    assert len(TELEGRAM_OPERATIONAL_ALLOWLIST) >= 10
