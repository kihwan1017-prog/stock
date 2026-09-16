"""LIVE_ARM_EXPIRED must not map to ORDER_REJECTED (Telegram safety alert)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from stock_platform.notification.events import NotificationEventType
from stock_platform.order.live_safety_audit import (
    LIVE_ARM_EXPIRED,
    LIVE_REJECTED,
    ORDER_AMOUNT_REJECT,
    ACTIVATION_EXPIRED,
    emit_live_order_telegram,
)


def test_live_arm_expired_maps_to_monitoring_alert_not_order_rejected() -> None:
    published: list[dict] = []

    class _Pub:
        def publish(self, **kwargs):
            published.append(kwargs)

    with patch(
        "stock_platform.notification.publisher.notification_publisher",
        _Pub(),
    ):
        emit_live_order_telegram(
            event_type=LIVE_ARM_EXPIRED,
            title="⚠️ 자동매매 승인 만료",
            message="계좌: 키움증권\n상태: ARM 만료",
            detail={
                "user_broker_account_id": 1381,
                "broker_code": "KIWOOM",
                "reason_ko": "ARM 승인 시간 만료로 LIVE가 안전하게 중지됨",
            },
        )

    assert len(published) == 1
    assert published[0]["event_type"] == NotificationEventType.MONITORING_ALERT.value
    assert published[0]["event_type"] != NotificationEventType.ORDER_REJECTED.value
    # symbol 없는 safety event — detail에 symbol 강제 없음
    assert "symbol" not in (published[0].get("detail") or {})
    assert "symbol_display" not in (published[0].get("detail") or {})


def test_activation_expired_maps_to_monitoring_alert() -> None:
    published: list[dict] = []

    class _Pub:
        def publish(self, **kwargs):
            published.append(kwargs)

    with patch(
        "stock_platform.notification.publisher.notification_publisher",
        _Pub(),
    ):
        emit_live_order_telegram(
            event_type=ACTIVATION_EXPIRED,
            title="Activation expired",
            message="LIVE session activation expired",
            detail={"user_broker_account_id": 1380, "reason_ko": "Activation 만료"},
        )

    assert published[0]["event_type"] == NotificationEventType.MONITORING_ALERT.value


def test_real_order_reject_still_maps_to_order_rejected() -> None:
    published: list[dict] = []

    class _Pub:
        def publish(self, **kwargs):
            published.append(kwargs)

    with patch(
        "stock_platform.notification.publisher.notification_publisher",
        _Pub(),
    ):
        emit_live_order_telegram(
            event_type=ORDER_AMOUNT_REJECT,
            title="❌ 주문 거부",
            message="amount exceeded",
            detail={
                "symbol": "034310",
                "symbol_display": "034310",
                "side_ko": "매수",
                "reason_ko": "주문금액 한도 초과",
            },
        )
        emit_live_order_telegram(
            event_type=LIVE_REJECTED,
            title="❌ 주문 거부",
            message="live rejected",
            detail={
                "symbol": "KRW-BTC",
                "symbol_display": "KRW-BTC",
                "side_ko": "매수",
                "reason_ko": "LIVE 게이트 거부",
            },
        )

    assert len(published) == 2
    assert all(
        p["event_type"] == NotificationEventType.ORDER_REJECTED.value
        for p in published
    )
