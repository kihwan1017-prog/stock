"""UPBIT limit 20 + Telegram user-facing alert UX tests."""

from __future__ import annotations

from datetime import datetime, timezone

from stock_platform.notification.code_dictionary import translate
from stock_platform.notification.formatting import format_datetime_kst
from stock_platform.notification.template_pipeline import render_notification
from stock_platform.notification.user_facing_alerts import (
    build_user_facing_copy,
    format_expires_kst,
    market_label_ko,
    reason_ko,
    should_coalesce_startup_monitoring,
)
from stock_platform.operation.upbit_full_market.constants import (
    DEFAULT_PORTFOLIO_DAILY_ENTRY_LIMIT,
)


def test_daily_limit_default_is_20() -> None:
    assert DEFAULT_PORTFOLIO_DAILY_ENTRY_LIMIT == 20


def test_market_label_from_broker_not_magic_uba() -> None:
    assert market_label_ko(broker_code="UPBIT") == "업비트"
    assert market_label_ko(broker_code="KIWOOM") == "키움증권"
    assert "1380" not in market_label_ko(broker_code="UPBIT")
    assert "1380" in market_label_ko(
        broker_code="UPBIT",
        user_broker_account_id=1380,
        include_uba_dev=True,
    )


def test_reason_korean_mapping() -> None:
    assert "안전" in reason_ko("fail_closed_restart")
    assert "자동 복구" in reason_ko("SYSTEM_UNATTENDED_STARTUP_RESTORE")
    assert "장 운영" in reason_ko("MARKET_HOURS_ARM_RESTORE")
    assert translate("DAILY_ENTRY_LIMIT_REACHED", group="alert_reason")


def test_utc_to_kst_format() -> None:
    utc = "2026-08-26T03:21:46.751899+00:00"
    out = format_expires_kst(utc)
    assert "2026-08-26 12:21" in out
    assert out.endswith("KST")
    assert "+00:00" not in out
    assert format_datetime_kst(utc).endswith("KST")


def test_disarm_user_copy() -> None:
    title, body, detail = build_user_facing_copy(
        event_type="MONITORING_ALERT",
        title="LIVE DISARM",
        message="UBA 1381 disarmed (fail_closed_restart) by STARTUP",
        detail={
            "user_broker_account_id": 1381,
            "broker_code": "KIWOOM",
            "reason": "fail_closed_restart",
            "actor": "STARTUP",
            "new_arm": False,
        },
    )
    assert "키움증권" in title
    assert "안전 해제" in title
    assert "fail_closed_restart" not in body
    assert "UBA 1381" not in body
    assert detail.get("_raw_reason") == "fail_closed_restart"


def test_arm_restore_user_copy_kst() -> None:
    title, body, _ = build_user_facing_copy(
        event_type="MONITORING_ALERT",
        title="LIVE ARM",
        message="UBA 1380 armed by SYSTEM_UNATTENDED_STARTUP_RESTORE until 2026-08-26T03:21:46.751899+00:00",
        detail={
            "user_broker_account_id": 1380,
            "broker_code": "UPBIT",
            "actor": "SYSTEM_UNATTENDED_STARTUP_RESTORE",
            "expires_at": "2026-08-26T03:21:46.751899+00:00",
            "new_arm": True,
            "live": True,
        },
    )
    assert "업비트" in title
    assert "복구 완료" in title
    assert "SYSTEM_UNATTENDED" not in body
    assert "+00:00" not in body
    assert "12:21" in body or "KST" in body


def test_daily_limit_reached_copy_uses_limit_20() -> None:
    title, body, _ = build_user_facing_copy(
        event_type="MONITORING_ALERT",
        title="limit",
        message="old",
        detail={
            "kind": "DAILY_LIMIT_REACHED",
            "entry_count": 20,
            "entry_limit": 20,
            "broker_code": "UPBIT",
        },
    )
    assert "20 / 20" in body
    assert "10 / 10" not in body
    assert "업비트" in title


def test_startup_coalesce_normal_disarm() -> None:
    suppressed, reason = should_coalesce_startup_monitoring(
        event_type="MONITORING_ALERT",
        detail={
            "reason": "fail_closed_restart",
            "actor": "STARTUP",
        },
        message="UBA 1380 disarmed (fail_closed_restart) by STARTUP",
    )
    assert suppressed is True
    assert reason == "STARTUP_NORMAL_DISARM_COALESCE"


def test_abnormal_disarm_not_coalesced() -> None:
    suppressed, _ = should_coalesce_startup_monitoring(
        event_type="MONITORING_ALERT",
        detail={"reason": "MANUAL", "actor": "ADMIN"},
        message="UBA 1380 disarmed (MANUAL) by ADMIN",
    )
    assert suppressed is False


def test_critical_not_coalesced() -> None:
    suppressed, _ = should_coalesce_startup_monitoring(
        event_type="KILL_SWITCH",
        detail={"reason": "fail_closed_restart", "actor": "STARTUP"},
        message="kill",
    )
    assert suppressed is False


def test_render_system_stop_friendly() -> None:
    rendered = render_notification(
        event_type="SYSTEM_STOP",
        title="System Stop",
        message="Application stopping",
        detail={"source": "ApplicationLifecycle"},
    )
    assert rendered.suppressed is False
    assert "서버 중지" in rendered.title
    assert "Application stopping" not in rendered.body


def test_render_startup_disarm_suppressed() -> None:
    rendered = render_notification(
        event_type="MONITORING_ALERT",
        title="LIVE DISARM",
        message="UBA 1381 disarmed (fail_closed_restart) by STARTUP",
        detail={
            "reason": "fail_closed_restart",
            "actor": "STARTUP",
            "broker_code": "KIWOOM",
            "user_broker_account_id": 1381,
        },
    )
    assert rendered.suppressed is True
