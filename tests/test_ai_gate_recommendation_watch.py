"""AI Gate recommendation watch / LIVE Preflight 대기 — 실주문 없음."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from stock_platform.realtime.ai_gate_recommendation_watch import (
    STATUS_BLOCKED_ACTIVATION,
    STATUS_BLOCKED_FEED,
    STATUS_BLOCKED_STALE,
    STATUS_HOLD,
    STATUS_READY,
    evaluate_ai_ready_for_live_preflight,
    emit_recommendation_changed,
    should_notify_recommendation_change,
)


def test_hold_to_hold_no_notify() -> None:
    assert should_notify_recommendation_change("HOLD", "HOLD") is False


def test_hold_to_allow_notifies() -> None:
    assert should_notify_recommendation_change("HOLD", "ALLOW") is True


def test_hold_to_reduce_notifies() -> None:
    assert should_notify_recommendation_change("HOLD", "REDUCE") is True


def test_allow_ready_when_infra_ok() -> None:
    out = evaluate_ai_ready_for_live_preflight(
        recommendation="ALLOW",
        fresh=True,
        analysis_status="VALIDATED_ANALYSIS",
        market_feed_ok=True,
        activation_ok=True,
    )
    assert out["status"] == STATUS_READY
    assert out["ready"] is True
    assert out["live_auto_start"] is False


def test_reduce_ready_when_infra_ok() -> None:
    out = evaluate_ai_ready_for_live_preflight(
        recommendation="REDUCE",
        fresh=True,
        analysis_status="VALIDATED_ANALYSIS",
        market_feed_ok=True,
        activation_ok=True,
    )
    assert out["status"] == STATUS_READY
    assert out["live_auto_start"] is False


def test_allow_blocked_when_feed_unhealthy() -> None:
    out = evaluate_ai_ready_for_live_preflight(
        recommendation="ALLOW",
        fresh=True,
        analysis_status="VALIDATED_ANALYSIS",
        market_feed_ok=False,
        activation_ok=True,
    )
    assert out["status"] == STATUS_BLOCKED_FEED
    assert out["ready"] is False
    assert "MARKET_FEED_UNHEALTHY" in out["blockers"]


def test_allow_blocked_when_activation_expired() -> None:
    out = evaluate_ai_ready_for_live_preflight(
        recommendation="ALLOW",
        fresh=True,
        analysis_status="VALIDATED_ANALYSIS",
        market_feed_ok=True,
        activation_ok=False,
    )
    assert out["status"] == STATUS_BLOCKED_ACTIVATION
    assert out["ready"] is False


def test_stale_ai_blocks() -> None:
    out = evaluate_ai_ready_for_live_preflight(
        recommendation="ALLOW",
        fresh=False,
        analysis_status="VALIDATED_ANALYSIS",
        market_feed_ok=True,
        activation_ok=True,
    )
    assert out["status"] == STATUS_BLOCKED_STALE
    assert out["ready"] is False


def test_hold_waiting_status() -> None:
    out = evaluate_ai_ready_for_live_preflight(
        recommendation="HOLD",
        fresh=True,
        analysis_status="VALIDATED_ANALYSIS",
        market_feed_ok=True,
        activation_ok=True,
    )
    assert out["status"] == STATUS_HOLD
    assert out["ready"] is False


def test_hold_ignores_feed_unhealthy_for_waiting_status() -> None:
    """HOLD 대기 중에는 Feed 장애로 READY를 막지 않고 HOLD로 유지."""

    out = evaluate_ai_ready_for_live_preflight(
        recommendation="HOLD",
        fresh=True,
        analysis_status="VALIDATED_ANALYSIS",
        market_feed_ok=False,
        activation_ok=False,
    )
    assert out["status"] == STATUS_HOLD
    assert out["ready"] is False
    assert out["blockers"] == []


def test_emit_hold_repeat_skips_audit_and_notify() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.order.live_safety_audit.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.notification.publisher.notification_publisher.publish"
        ) as pub,
    ):
        out = emit_recommendation_changed(
            session,
            previous="HOLD",
            current="HOLD",
            user_broker_account_id=1380,
            strategy_id=17483,
            symbol="KRW-XRP",
            analysis_id=1,
            trend="SIDEWAYS",
            momentum="NEUTRAL",
            volatility="LOW",
            confidence=0.85,
            analysis_at="2026-08-13T00:00:00+09:00",
            preflight_status=STATUS_HOLD,
        )
    assert out["emitted"] is False
    audit.assert_not_called()
    pub.assert_not_called()


def test_emit_hold_to_allow_records_audit_and_notify() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.order.live_safety_audit.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.notification.publisher.notification_publisher.publish"
        ) as pub,
    ):
        out = emit_recommendation_changed(
            session,
            previous="HOLD",
            current="ALLOW",
            user_broker_account_id=1380,
            strategy_id=17483,
            symbol="KRW-XRP",
            analysis_id=99,
            trend="UPTREND",
            momentum="BULLISH",
            volatility="LOW",
            confidence=0.9,
            analysis_at="2026-08-13T00:00:00+09:00",
            preflight_status=STATUS_READY,
        )
    assert out["emitted"] is True
    assert out["detail"]["live_auto_start"] is False
    audit.assert_called_once()
    pub.assert_called_once()
    assert pub.call_args.kwargs["detail"]["new_recommendation"] == "ALLOW"
