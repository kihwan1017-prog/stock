"""Unattended activation successor — AUTO 보호 SELL open은 validate 통과."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.broker.live_transition_models import (
    LiveTransitionCheckCode,
    LiveTransitionCheckStatus,
)
from stock_platform.trading.live_unattended_authorization_service import (
    LiveUnattendedAuthorizationService,
    LiveUnattendedError,
)


def test_create_successor_passes_allow_auto_protective_flag() -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
    )
    previous = SimpleNamespace(
        max_order_amount=Decimal("5100"),
        max_daily_loss=Decimal("100000"),
        live_trading_transition_id=128,
    )
    seen: dict = {}

    class _Plan:
        ready = True
        checks = []

    class _FakeTransitionSvc:
        def validate(self, **kwargs):  # noqa: ANN003
            seen["validate"] = kwargs
            return _Plan()

        def request_transition(self, **kwargs):  # noqa: ANN003
            seen["request"] = kwargs
            return SimpleNamespace(live_trading_transition_id=999)

    with (
        patch(
            "stock_platform.trading.live_unattended_authorization_service."
            "LiveTradingTransitionService",
            return_value=_FakeTransitionSvc(),
        ),
        patch.object(
            svc,
            "_approve_successor_internal",
            return_value=SimpleNamespace(live_trading_transition_id=999),
        ),
    ):
        out = svc._create_successor_activation(
            uba=uba,
            previous=previous,
            actor="SYSTEM_UNATTENDED_RESTORE",
            ttl_hours=8,
        )

    assert out.live_trading_transition_id == 999
    assert seen["validate"].get("allow_auto_protective_open_orders") is True
    assert seen["request"].get("allow_auto_protective_open_orders") is True


def test_create_successor_error_includes_failing_checks() -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    uba = SimpleNamespace(user_broker_account_id=1380, broker_code="UPBIT")
    previous = SimpleNamespace(
        max_order_amount=Decimal("5100"),
        max_daily_loss=Decimal("100000"),
        live_trading_transition_id=128,
    )

    class _FailPlan:
        ready = False
        checks = [
            SimpleNamespace(
                code=LiveTransitionCheckCode.NO_DB_OPEN_ORDERS,
                status=LiveTransitionCheckStatus.FAIL,
                message="db_open_orders=0",
            )
        ]

    class _FakeTransitionSvc:
        def validate(self, **_kwargs):  # noqa: ANN003
            return _FailPlan()

    with patch(
        "stock_platform.trading.live_unattended_authorization_service."
        "LiveTradingTransitionService",
        return_value=_FakeTransitionSvc(),
    ):
        try:
            svc._create_successor_activation(
                uba=uba,
                previous=previous,
                actor="SYSTEM_UNATTENDED_RESTORE",
                ttl_hours=8,
            )
            raise AssertionError("expected LiveUnattendedError")
        except LiveUnattendedError as exc:
            assert exc.code == "ACTIVATION_VALIDATE_FAILED"
            assert "NO_DB_OPEN_ORDERS" in exc.message
