"""STEP 8-5-21 — RC blocker removal / LIVE gate tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.live_config_gate import (
    evaluate_live_flag_consistency,
)
from stock_platform.broker.live_order_dry_run import (
    LiveOrderDryRunService,
)
from stock_platform.broker.live_transition_entities import (
    LiveTradingTransitionEntity,
)
from stock_platform.broker.live_transition_service import (
    LiveTradingTransitionService,
)
from tests.migration_helpers import (
    alembic_current_head,
    assert_revision_exists,
)


def test_step8_5_21_revision_head() -> None:
    assert_revision_exists("i2c3d4e5f6a7")
    head = alembic_current_head()
    assert_revision_exists(head)


def test_live_flag_mismatch_global_off_kiwoom_on(monkeypatch) -> None:
    from stock_platform.common import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    settings_mod.get_settings.cache_clear()
    result = evaluate_live_flag_consistency()
    assert result.code == "LIVE_FLAG_MISMATCH_KIWOOM"
    assert result.allowed is False
    settings_mod.get_settings.cache_clear()


def test_live_flag_mock_conflict(monkeypatch) -> None:
    from stock_platform.common import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    settings_mod.get_settings.cache_clear()
    result = evaluate_live_flag_consistency()
    assert result.code == "LIVE_MOCK_CONFLICT"
    assert result.allowed is False
    settings_mod.get_settings.cache_clear()


def test_activation_missing_expires_disables(monkeypatch) -> None:
    session = MagicMock()
    entity = LiveTradingTransitionEntity(
        requested_by="t",
        max_order_amount=Decimal("1000"),
        max_daily_loss=Decimal("1000"),
        enabled=True,
        expires_at=None,
        activation_status="ACTIVE",
    )
    session.scalars.return_value = [entity]
    service = LiveTradingTransitionService(session)
    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.TradingSchedulerControlService"
        ),
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
    ):
        assert service.get_active() is None
    assert entity.enabled is False
    assert entity.activation_status == "EXPIRED"


def test_activation_expired_disables() -> None:
    session = MagicMock()
    entity = LiveTradingTransitionEntity(
        requested_by="t",
        max_order_amount=Decimal("1000"),
        max_daily_loss=Decimal("1000"),
        enabled=True,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        activation_status="ACTIVE",
    )
    session.scalars.return_value = [entity]
    service = LiveTradingTransitionService(session)
    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.TradingSchedulerControlService"
        ),
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_session_expiry.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
    ):
        assert service.get_active() is None
    assert entity.activation_status == "EXPIRED"


def test_live_dry_run_never_calls_broker(monkeypatch) -> None:
    session = MagicMock()
    session.scalar.side_effect = [0, 0, None]  # health counts + activation

    from stock_platform.operation import live_health_gate as gate

    monkeypatch.setattr(
        gate,
        "evaluate_live_order_health",
        lambda _s: {
            "status": "HEALTHY",
            "live_orders_allowed": True,
            "uba_missing_active_snapshot_count": 0,
            "daily_loss_missing_scope_count": 0,
        },
    )
    result = LiveOrderDryRunService(session).run(
        user_id=1,
        user_broker_account_id=1,
        symbol="005930",
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("70000"),
        broker_code="KIWOOM",
    )
    assert result.broker_endpoint_called is False
    assert "ACTIVATION_MISSING_OR_EXPIRED" in result.blocked_by
