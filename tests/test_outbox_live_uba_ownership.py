"""Outbox LIVE dispatch — UBA ownership / PaperAccount 미조회 회귀."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.outbox_worker import OrderOutboxWorker


def test_live_dispatch_requires_matching_uba_broker_and_owner() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=42,
        user_id=7,
        broker_code="UPBIT",
        is_active=True,
        live_order_enabled=True,
        live_armed=True,
    )
    session.get.return_value = uba

    payload = {
        "environment": "LIVE",
        "broker_code": "UPBIT",
        "user_broker_account_id": 42,
        "owner_user_id": 7,
        "account_id": None,
    }

    with (
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard"
        ) as Guard,
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService"
        ) as Arm,
    ):
        Guard.return_value.require_active = MagicMock()
        Arm.return_value.expire_if_needed.return_value = False
        OrderOutboxWorker._assert_live_dispatch_allowed(session, payload)

    # UserBrokerAccount 만 조회 (PaperAccount 아님)
    assert session.get.call_count >= 1
    first_target = session.get.call_args_list[0].args[0]
    assert getattr(first_target, "__name__", "") == "UserBrokerAccount"


def test_live_dispatch_blocks_owner_mismatch() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        user_id=99,
        broker_code="UPBIT",
        is_active=True,
        live_order_enabled=True,
        live_armed=True,
    )
    with (
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard"
        ) as Guard,
    ):
        Guard.return_value.require_active = MagicMock()
        with pytest.raises(PermissionError, match="UBA_OWNERSHIP_MISMATCH"):
            OrderOutboxWorker._assert_live_dispatch_allowed(
                session,
                {
                    "environment": "LIVE",
                    "broker_code": "UPBIT",
                    "user_broker_account_id": 42,
                    "owner_user_id": 7,
                },
            )


def test_live_dispatch_blocks_broker_mismatch() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        user_id=7,
        broker_code="KIWOOM",
        is_active=True,
        live_order_enabled=True,
        live_armed=True,
    )
    with (
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard"
        ) as Guard,
    ):
        Guard.return_value.require_active = MagicMock()
        with pytest.raises(PermissionError, match="UBA_BROKER_MISMATCH"):
            OrderOutboxWorker._assert_live_dispatch_allowed(
                session,
                {
                    "environment": "LIVE",
                    "broker_code": "UPBIT",
                    "user_broker_account_id": 42,
                    "owner_user_id": 7,
                },
            )
