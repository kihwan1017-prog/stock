"""Telegram market routing + ANALYSIS suppression tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.notification.telegram_policy import (
    TelegramCategory,
    TelegramMarket,
    _EDGE_STATE,
    evaluate_telegram_policy,
    map_telegram_category,
    mask_chat_id,
    maybe_emit_upbit_daily_limit_edge,
    resolve_telegram_chat_id,
    resolve_telegram_market,
)


def setup_function() -> None:
    _EDGE_STATE.clear()


def test_category_mapping() -> None:
    assert map_telegram_category("UPBIT_SCANNER_CANDIDATE") == TelegramCategory.ANALYSIS
    assert map_telegram_category("ORDER_FILLED") == TelegramCategory.TRADING
    assert map_telegram_category("STOP_LOSS") == TelegramCategory.TRADING
    assert map_telegram_category("KILL_SWITCH") == TelegramCategory.CRITICAL
    assert map_telegram_category("RUNTIME_STARTED") == TelegramCategory.SYSTEM


def test_market_resolve() -> None:
    assert (
        resolve_telegram_market(
            event_type="UPBIT_SCANNER_CANDIDATE", detail={}
        )
        == TelegramMarket.UPBIT
    )
    assert (
        resolve_telegram_market(
            event_type="MONITORING_ALERT",
            detail={"broker_code": "KIWOOM"},
        )
        == TelegramMarket.KIWOOM
    )


def test_chat_routing_fallback(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "fallback-chat")
    monkeypatch.setenv("TELEGRAM_UPBIT_CHAT_ID", "upbit-chat")
    monkeypatch.setenv("TELEGRAM_KIWOOM_CHAT_ID", "")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        chat_u, route_u = resolve_telegram_chat_id(TelegramMarket.UPBIT)
        chat_k, route_k = resolve_telegram_chat_id(TelegramMarket.KIWOOM)
        assert chat_u == "upbit-chat" and route_u == "UPBIT"
        assert chat_k == "fallback-chat" and route_k == "FALLBACK"
        assert mask_chat_id(chat_u) is not None
        assert "upbit-chat" not in (mask_chat_id(chat_u) or "")
    finally:
        get_settings.cache_clear()


def test_upbit_analysis_suppress_at_limit() -> None:
    usage = {
        "entry_count": 10,
        "entry_limit": 10,
        "blocking": True,
    }
    with patch(
        "stock_platform.notification.telegram_policy._upbit_daily_usage",
        return_value=usage,
    ):
        d = evaluate_telegram_policy(
            event_type="UPBIT_SCANNER_CANDIDATE",
            detail={"broker_code": "UPBIT", "user_broker_account_id": 1380},
            session=MagicMock(),
        )
    assert d.allowed is False
    assert d.reason == "DAILY_ENTRY_LIMIT_REACHED"


def test_upbit_analysis_allow_under_limit() -> None:
    usage = {"entry_count": 9, "entry_limit": 10, "blocking": False}
    with patch(
        "stock_platform.notification.telegram_policy._upbit_daily_usage",
        return_value=usage,
    ):
        d = evaluate_telegram_policy(
            event_type="AI_ANALYSIS_COMPLETE",
            detail={"broker_code": "UPBIT"},
            session=MagicMock(),
        )
    assert d.allowed is True


def test_upbit_legacy_12_suppress() -> None:
    usage = {"entry_count": 12, "entry_limit": 10, "blocking": True}
    with patch(
        "stock_platform.notification.telegram_policy._upbit_daily_usage",
        return_value=usage,
    ):
        d = evaluate_telegram_policy(
            event_type="UPBIT_SCANNER_CANDIDATE",
            detail={"broker_code": "UPBIT"},
            session=MagicMock(),
        )
    assert d.allowed is False


def test_upbit_limit_trading_and_critical_still_allowed() -> None:
    usage = {"entry_count": 12, "entry_limit": 10, "blocking": True}
    with patch(
        "stock_platform.notification.telegram_policy._upbit_daily_usage",
        return_value=usage,
    ):
        sell = evaluate_telegram_policy(
            event_type="ORDER_FILLED",
            detail={"broker_code": "UPBIT", "side": "SELL"},
            session=MagicMock(),
        )
        stop = evaluate_telegram_policy(
            event_type="STOP_LOSS",
            detail={"broker_code": "UPBIT"},
            session=MagicMock(),
        )
        crit = evaluate_telegram_policy(
            event_type="BROKER_DISCONNECTED",
            detail={"broker_code": "UPBIT"},
            session=MagicMock(),
        )
        system = evaluate_telegram_policy(
            event_type="MONITORING_ALERT",
            detail={"broker_code": "UPBIT", "kind": "DAILY_LIMIT_REACHED"},
            session=MagicMock(),
        )
    assert sell.allowed and stop.allowed and crit.allowed and system.allowed


def test_kiwoom_analysis_suppress_when_closed() -> None:
    with patch(
        "stock_platform.notification.telegram_policy._kiwoom_trading_ready",
        return_value=(False, "MARKET_CLOSED", {}),
    ):
        d = evaluate_telegram_policy(
            event_type="AI_ANALYSIS_COMPLETE",
            detail={"broker_code": "KIWOOM"},
            session=MagicMock(),
        )
    assert d.allowed is False
    assert d.reason == "MARKET_CLOSED"


def test_kiwoom_closed_critical_still_allowed() -> None:
    with patch(
        "stock_platform.notification.telegram_policy._kiwoom_trading_ready",
        return_value=(False, "MARKET_CLOSED", {}),
    ):
        d = evaluate_telegram_policy(
            event_type="KILL_SWITCH",
            detail={"broker_code": "KIWOOM"},
            session=MagicMock(),
        )
    assert d.allowed is True


def test_kiwoom_open_but_runtime_stopped_suppress() -> None:
    with patch(
        "stock_platform.notification.telegram_policy._kiwoom_trading_ready",
        return_value=(False, "RUNTIME_STOPPED", {"runtime": "STOPPED"}),
    ):
        d = evaluate_telegram_policy(
            event_type="UPBIT_SCANNER_CANDIDATE",  # wrong market — use KIWOOM detail
            detail={"broker_code": "KIWOOM"},
            session=MagicMock(),
        )
    # market from detail is KIWOOM; ANALYSIS suppress
    assert map_telegram_category("AI_ANALYSIS_COMPLETE") == TelegramCategory.ANALYSIS
    d2 = evaluate_telegram_policy(
        event_type="AI_ANALYSIS_COMPLETE",
        detail={"broker_code": "KIWOOM"},
        session=MagicMock(),
    )
    # still patched
    with patch(
        "stock_platform.notification.telegram_policy._kiwoom_trading_ready",
        return_value=(False, "RUNTIME_STOPPED", {}),
    ):
        d2 = evaluate_telegram_policy(
            event_type="AI_ANALYSIS_COMPLETE",
            detail={"broker_code": "KIWOOM"},
            session=MagicMock(),
        )
    assert d2.allowed is False
    assert d2.reason == "RUNTIME_STOPPED"


def test_daily_limit_edge_dedup() -> None:
    published: list[str] = []

    def fake_publish(*, event_type, title, message, detail=None, dispatch=True):
        published.append(str((detail or {}).get("kind")))
        return SimpleNamespace()

    with patch(
        "stock_platform.notification.publisher.notification_publisher.publish",
        side_effect=fake_publish,
    ):
        a = maybe_emit_upbit_daily_limit_edge(
            usage={"blocking": True, "entry_count": 12, "entry_limit": 10}
        )
        b = maybe_emit_upbit_daily_limit_edge(
            usage={"blocking": True, "entry_count": 12, "entry_limit": 10}
        )
    assert a == "DAILY_LIMIT_REACHED"
    assert b is None
    assert published.count("DAILY_LIMIT_REACHED") == 1


def test_routing_no_cross_market(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "fallback-chat")
    monkeypatch.setenv("TELEGRAM_UPBIT_CHAT_ID", "upbit-only")
    monkeypatch.setenv("TELEGRAM_KIWOOM_CHAT_ID", "kiwoom-only")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        u, ru = resolve_telegram_chat_id(TelegramMarket.UPBIT)
        k, rk = resolve_telegram_chat_id(TelegramMarket.KIWOOM)
        assert u == "upbit-only" and ru == "UPBIT"
        assert k == "kiwoom-only" and rk == "KIWOOM"
        assert u != k
    finally:
        get_settings.cache_clear()


def test_kiwoom_ready_allows_analysis() -> None:
    with patch(
        "stock_platform.notification.telegram_policy._kiwoom_trading_ready",
        return_value=(True, None, {"lifecycle_phase": "TRADING"}),
    ):
        d = evaluate_telegram_policy(
            event_type="AI_ANALYSIS_COMPLETE",
            detail={"broker_code": "KIWOOM"},
            session=MagicMock(),
        )
    assert d.allowed is True
    assert d.reason == "KIWOOM_TRADING_READY"


def test_next_day_available_allows_analysis() -> None:
    usage = {"entry_count": 0, "entry_limit": 10, "blocking": False}
    with patch(
        "stock_platform.notification.telegram_policy._upbit_daily_usage",
        return_value=usage,
    ):
        d = evaluate_telegram_policy(
            event_type="UPBIT_SCANNER_CANDIDATE",
            detail={"broker_code": "UPBIT"},
            session=MagicMock(),
        )
    assert d.allowed is True


def test_service_dispatch_wires_policy() -> None:
    import inspect

    from stock_platform.notification import service as svc

    src = inspect.getsource(svc.NotificationService.dispatch)
    assert "evaluate_telegram_policy" in src
    assert "telegram_chat_id" in src
