"""Kiwoom / trading block notification dedupe — gate 평가와 분리."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.notification.template_pipeline import (
    _state_dedupe,
    render_notification,
    should_suppress_state_event,
)
from stock_platform.trading.live_unattended_authorization_service import (
    STATUS_ACTIVE,
    STATUS_PROTECTIVE,
    LiveUnattendedAuthorizationService,
)


@pytest.fixture(autouse=True)
def _clear_state_dedupe() -> None:
    _state_dedupe.clear()


def test_first_blocked_delivers_once() -> None:
    detail = {
        "broker_code": "KIWOOM",
        "user_broker_account_id": 1381,
        "reason": "HORIZON_EXPIRED",
    }
    rendered = render_notification(
        event_type="UNATTENDED_ENTRY_BLOCKED",
        title="blocked",
        message="blocked",
        detail=detail,
    )
    assert rendered.suppressed is False


def test_same_blocker_repeat_suppressed() -> None:
    detail = {
        "broker_code": "KIWOOM",
        "user_broker_account_id": 1381,
        "strategy_id": "17579",
        "symbol": "005930",
        "reason": "HORIZON_EXPIRED",
    }
    variables = {"uba_id": "1381", "broker_code": "KIWOOM", "symbol": "005930"}
    first, _ = should_suppress_state_event(
        event_type="UNATTENDED_ENTRY_BLOCKED",
        variables=variables,
        detail=detail,
    )
    second, reason = should_suppress_state_event(
        event_type="UNATTENDED_ENTRY_BLOCKED",
        variables=variables,
        detail=detail,
    )
    assert first is False
    assert second is True
    assert reason == "TRADING_BLOCK_STATE_DEDUPE"


def test_reason_change_not_suppressed() -> None:
    base = {
        "broker_code": "KIWOOM",
        "user_broker_account_id": 1381,
        "symbol": "005930",
    }
    variables = {"uba_id": "1381", "broker_code": "KIWOOM", "symbol": "005930"}
    should_suppress_state_event(
        event_type="LIVE_REJECTED",
        variables=variables,
        detail={**base, "reason_code": "UNATTENDED_ENTRY_BLOCKED"},
    )
    suppressed, _ = should_suppress_state_event(
        event_type="LIVE_REJECTED",
        variables=variables,
        detail={**base, "reason_code": "KILL_SWITCH_ACTIVE"},
    )
    assert suppressed is False


def test_symbol_change_independent() -> None:
    variables = {"uba_id": "1381", "broker_code": "KIWOOM"}
    should_suppress_state_event(
        event_type="LIVE_REJECTED",
        variables={**variables, "symbol": "005930"},
        detail={
            "broker_code": "KIWOOM",
            "user_broker_account_id": 1381,
            "symbol": "005930",
            "reason_code": "LIVE_ORDER_DISABLED",
        },
    )
    suppressed, reason = should_suppress_state_event(
        event_type="LIVE_REJECTED",
        variables={**variables, "symbol": "000660"},
        detail={
            "broker_code": "KIWOOM",
            "user_broker_account_id": 1381,
            "symbol": "000660",
            "reason_code": "LIVE_ORDER_DISABLED",
        },
    )
    assert suppressed is False
    assert reason is None


def test_kill_switch_monitoring_alert_dedupe() -> None:
    detail = {"rule_id": "KILL_SWITCH_ACTIVATED", "message": "kill switch active"}
    first, _ = should_suppress_state_event(
        event_type="MONITORING_ALERT",
        variables={},
        detail=detail,
    )
    second, reason = should_suppress_state_event(
        event_type="MONITORING_ALERT",
        variables={},
        detail=detail,
    )
    assert first is False
    assert second is True
    assert reason == "TRADING_BLOCK_STATE_DEDUPE"


def test_entry_wait_reason_never_telegram() -> None:
    suppressed, reason = should_suppress_state_event(
        event_type="LIVE_REJECTED",
        variables={"symbol": "005930", "uba_id": "1381"},
        detail={
            "broker_code": "KIWOOM",
            "user_broker_account_id": 1381,
            "reason_code": "NO_FRESH_GOLDEN_CROSS",
        },
    )
    assert suppressed is True
    assert reason == "ENTRY_WAIT_OBSERVABILITY_ONLY"


def test_upbit_regression_unchanged_ai_hold() -> None:
    suppressed, reason = should_suppress_state_event(
        event_type="AI_GATE_RECOMMENDATION_CHANGED",
        variables={
            "previous_recommendation_ko": "대기",
            "new_recommendation_ko": "대기",
            "symbol": "XRP",
            "uba_id": "1380",
        },
        detail={},
    )
    assert suppressed is True
    assert reason == "AI_RECOMMENDATION_UNCHANGED"


def test_expire_authorization_idempotent_when_already_protective() -> None:
    session = MagicMock()
    row = SimpleNamespace(
        live_unattended_authorization_id=14,
        user_broker_account_id=1381,
        enabled=True,
        status_code=STATUS_PROTECTIVE,
        entry_authorized=False,
        protective_exit_authorized=True,
        authorized_until=None,
        revoked_at=None,
        revoked_by=None,
        revoke_reason="HORIZON_EXPIRED",
        updated_at=None,
    )
    svc = LiveUnattendedAuthorizationService(session)
    with patch.object(svc, "_fail_closed_on_expiry") as fail_closed, patch(
        "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
    ) as audit:
        svc._expire_authorization(row, actor="SYSTEM", reason="HORIZON_EXPIRED")
    fail_closed.assert_not_called()
    audit.assert_not_called()


def test_expire_authorization_first_transition_from_active() -> None:
    session = MagicMock()
    row = SimpleNamespace(
        live_unattended_authorization_id=14,
        user_broker_account_id=1381,
        enabled=True,
        status_code=STATUS_ACTIVE,
        entry_authorized=True,
        protective_exit_authorized=True,
        authorized_until=None,
        revoked_at=None,
        revoked_by=None,
        revoke_reason=None,
        updated_at=None,
    )
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "_has_open_position", return_value=True),
        patch.object(svc, "_fail_closed_on_expiry"),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ) as audit,
    ):
        svc._expire_authorization(row, actor="SYSTEM", reason="HORIZON_EXPIRED")
    assert row.status_code == STATUS_PROTECTIVE
    assert row.entry_authorized is False
    audit.assert_called_once()
