"""Design A — ARM authorization without plaintext token for Confirm."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.live_arm_service import LiveArmService


def _uba(
    *,
    live: bool = True,
    armed: bool = True,
    token_hash: str | None = "hash",
    expires_in: int | None = 300,
    uba_id: int = 1380,
    user_id: int = 61,
):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        user_broker_account_id=uba_id,
        user_id=user_id,
        is_active=True,
        live_order_enabled=live,
        live_armed=armed,
        arm_token_hash=token_hash,
        arm_expires_at=(
            now + timedelta(seconds=expires_in)
            if expires_in is not None
            else None
        ),
        live_approved_at=now if live else None,
        live_approved_by="admin" if live else None,
    )


def _svc(uba) -> LiveArmService:
    session = MagicMock()
    session.get.return_value = uba
    return LiveArmService(session)


def test_state_only_pass_when_armed() -> None:
    uba = _uba()
    ok, reason = _svc(uba).validate_arm_authorization(
        1380, arm_token=None, require_token_challenge=False
    )
    assert ok is True
    assert reason == "ARM_OK"


def test_expired_arm_fails() -> None:
    uba = _uba(expires_in=-10)
    with patch.object(
        LiveArmService, "_expire_if_needed", return_value=True
    ):
        ok, reason = _svc(uba).validate_arm_authorization(1380)
    assert ok is False
    assert reason == "LIVE_ARM_EXPIRED"


def test_disarmed_fails() -> None:
    uba = _uba(armed=False, token_hash=None)
    ok, reason = _svc(uba).validate_arm_authorization(1380)
    assert ok is False
    assert reason == "LIVE_NOT_ARMED"


def test_live_off_fails() -> None:
    uba = _uba(live=False)
    ok, reason = _svc(uba).validate_arm_authorization(1380)
    assert ok is False
    assert reason == "LIVE_ORDER_DISABLED"


def test_wrong_token_challenge_fails() -> None:
    plain = "correct-token"
    uba = _uba(token_hash=LiveArmService.hash_token(plain))
    ok, reason = _svc(uba).validate_arm_authorization(
        1380, arm_token="wrong", require_token_challenge=False
    )
    assert ok is False
    assert reason == "ARM_TOKEN_MISMATCH"


def test_require_token_challenge_missing_fails() -> None:
    uba = _uba()
    ok, reason = _svc(uba).validate_arm_authorization(
        1380, arm_token=None, require_token_challenge=True
    )
    assert ok is False
    assert reason == "ARM_TOKEN_MISSING"


def test_legacy_validate_arm_token_requires_challenge() -> None:
    plain = "tok-once"
    uba = _uba(token_hash=LiveArmService.hash_token(plain))
    ok, _ = _svc(uba).validate_arm_token(1380, plain)
    assert ok is True
    ok2, reason = _svc(uba).validate_arm_token(1380, None)
    assert ok2 is False
    assert reason == "ARM_TOKEN_MISSING"


def test_confirm_execute_live_blocks_without_activation() -> None:
    """execute_live Confirm — Activation 없으면 Fail Closed (주문 미생성)."""

    from stock_platform.trading.controlled_live_order_smoke_service import (
        ControlledLiveOrderSmokeError,
        ControlledLiveOrderSmokeService,
    )

    session = MagicMock()
    svc = ControlledLiveOrderSmokeService(session)
    svc._load_owned_upbit = MagicMock(
        return_value=SimpleNamespace(
            user_broker_account_id=1380, user_id=61, broker_code="UPBIT"
        )
    )
    svc._assert_runtime_stopped = MagicMock()
    svc._assert_order_test_fresh = MagicMock()

    with patch(
        "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard.require_active",
        side_effect=PermissionError("No active live trading transition approval"),
    ):
        with pytest.raises(ControlledLiveOrderSmokeError) as ei:
            svc.confirm(
                uba_id=1380,
                user_id=61,
                actor="user",
                market="KRW-XRP",
                side="BUY",
                amount=__import__("decimal").Decimal("5000"),
                limit_price=__import__("decimal").Decimal("1435"),
                confirmation_text="UPBIT LIVE BUY CONFIRM",
                arm_token=None,
                execute_live=True,
                order_test_fingerprint="fp",
                order_test_tested_at=datetime.now(timezone.utc).isoformat(),
            )
    assert ei.value.code == "ACTIVATION_INACTIVE"


def test_confirm_execute_live_blocks_when_disarmed() -> None:
    from decimal import Decimal

    from stock_platform.trading.controlled_live_order_smoke_service import (
        ControlledLiveOrderSmokeError,
        ControlledLiveOrderSmokeService,
    )

    session = MagicMock()
    svc = ControlledLiveOrderSmokeService(session)
    svc._load_owned_upbit = MagicMock(
        return_value=SimpleNamespace(
            user_broker_account_id=1380, user_id=61, broker_code="UPBIT"
        )
    )
    svc._assert_runtime_stopped = MagicMock()
    svc._assert_order_test_fresh = MagicMock()

    with (
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard.require_active",
            return_value=SimpleNamespace(),
        ),
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService.validate_arm_authorization",
            return_value=(False, "LIVE_NOT_ARMED"),
        ),
    ):
        with pytest.raises(ControlledLiveOrderSmokeError) as ei:
            svc.confirm(
                uba_id=1380,
                user_id=61,
                actor="user",
                market="KRW-XRP",
                side="BUY",
                amount=Decimal("5000"),
                limit_price=Decimal("1435"),
                confirmation_text="UPBIT LIVE BUY CONFIRM",
                arm_token=None,
                execute_live=True,
                order_test_fingerprint="fp",
                order_test_tested_at=datetime.now(timezone.utc).isoformat(),
            )
    assert ei.value.code == "LIVE_NOT_ARMED"


def test_ownership_forbidden_before_arm() -> None:
    from decimal import Decimal

    from stock_platform.trading.controlled_live_order_smoke_service import (
        ControlledLiveOrderSmokeError,
        ControlledLiveOrderSmokeService,
    )

    session = MagicMock()
    svc = ControlledLiveOrderSmokeService(session)
    svc._load_owned_upbit = MagicMock(
        side_effect=ControlledLiveOrderSmokeError("FORBIDDEN")
    )
    with pytest.raises(ControlledLiveOrderSmokeError) as ei:
        svc.confirm(
            uba_id=9999,
            user_id=61,
            actor="user",
            market="KRW-XRP",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("1435"),
            confirmation_text="UPBIT LIVE BUY CONFIRM",
            arm_token=None,
            execute_live=True,
        )
    assert ei.value.code == "FORBIDDEN"
