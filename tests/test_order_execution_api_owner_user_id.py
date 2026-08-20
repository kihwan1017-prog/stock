"""LIVE order-execution submit: downstream user_id = UBA owner (admin JWT 아님)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, status

from stock_platform.api.v1.order_execution import (
    SubmitOrderRequest,
    submit_order,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.order.execution_service import OrderExecutionResult
from stock_platform.order.models import OrderSide, OrderType


def _admin() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=7,
        username="admin",
        roles=["admin"],
        permissions=["trading:write"],
    )


def _owner_uba(*, uba_id: int = 1381, owner_user_id: int = 61) -> SimpleNamespace:
    return SimpleNamespace(
        user_broker_account_id=uba_id,
        user_id=owner_user_id,
        broker_code="KIWOOM",
        is_active=True,
        masked_account_number="****1234",
    )


def _req(**kwargs: object) -> SubmitOrderRequest:
    payload = {
        "account_id": 1,
        "user_broker_account_id": 1381,
        "broker_code": "KIWOOM",
        "exchange_code": "KRX",
        "environment": "LIVE",
        "symbol": "034310",
        "side": OrderSide.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": Decimal("1"),
        "price": Decimal("13000"),
    }
    payload.update(kwargs)
    return SubmitOrderRequest(**payload)  # type: ignore[arg-type]


def test_admin_live_submit_uses_uba_owner_user_id() -> None:
    """ADMIN JWT(user_id=7)로 USER(61) UBA 주문 시 command.user_id=61."""

    captured: dict = {}

    def _fake_submit(self, command):  # noqa: ANN001
        captured["command"] = command
        return OrderExecutionResult(
            allowed=True,
            reason_code="OK",
            order_id=1,
            outbox_id=1,
            status_code="PENDING",
            client_order_id="cid-1",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            position_plan=None,
        )

    http_request = MagicMock()
    http_request.state = SimpleNamespace(request_id="r1")
    http_request.client = SimpleNamespace(host="127.0.0.1")
    http_request.headers = {}

    with (
        patch(
            "stock_platform.api.v1.order_execution.assert_paper_account_access",
            return_value=SimpleNamespace(account_id=1),
        ),
        patch(
            "stock_platform.api.v1.order_execution.assert_active_broker_account_for_trading",
            return_value=_owner_uba(uba_id=1381, owner_user_id=61),
        ),
        patch(
            "stock_platform.api.v1.order_execution.require_live_broker_account_id",
            return_value=None,
        ),
        patch(
            "stock_platform.api.v1.order_execution.enforce_rate_limit",
            return_value=None,
        ),
        patch(
            "stock_platform.order.execution_service.OrderExecutionService.submit",
            _fake_submit,
        ),
    ):
        result = submit_order(
            _req(),
            http_request,
            user=_admin(),
            session=MagicMock(),
        )

    assert result["allowed"] is True
    cmd = captured["command"]
    assert int(cmd.user_id) == 61
    assert int(cmd.owner_user_id) == 61
    assert int(cmd.user_broker_account_id) == 1381
    # request.actor 기본값 "API"가 있으면 유지 (username 대체는 actor 비어 있을 때)
    assert cmd.actor in {"API", "admin"}
    # 핵심: JWT admin(7)이 아니라 UBA owner(61)
    assert int(cmd.user_id) != 7


def test_admin_live_submit_other_uba_uses_that_owner() -> None:
    """다른 UBA면 해당 owner로 전달 — 계좌별 generic."""

    captured: dict = {}

    def _fake_submit(self, command):  # noqa: ANN001
        captured["command"] = command
        return OrderExecutionResult(
            allowed=True,
            reason_code="OK",
            order_id=2,
            outbox_id=2,
            status_code="PENDING",
            client_order_id="cid-2",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            position_plan=None,
        )

    http_request = MagicMock()
    with (
        patch(
            "stock_platform.api.v1.order_execution.assert_paper_account_access",
            return_value=SimpleNamespace(account_id=1),
        ),
        patch(
            "stock_platform.api.v1.order_execution.assert_active_broker_account_for_trading",
            return_value=_owner_uba(uba_id=9999, owner_user_id=42),
        ),
        patch(
            "stock_platform.api.v1.order_execution.require_live_broker_account_id",
            return_value=None,
        ),
        patch(
            "stock_platform.api.v1.order_execution.enforce_rate_limit",
            return_value=None,
        ),
        patch(
            "stock_platform.order.execution_service.OrderExecutionService.submit",
            _fake_submit,
        ),
    ):
        submit_order(
            _req(user_broker_account_id=9999, symbol="005930", price=Decimal("70000")),
            http_request,
            user=_admin(),
            session=MagicMock(),
        )

    cmd = captured["command"]
    assert int(cmd.user_id) == 42
    assert int(cmd.owner_user_id) == 42
    assert int(cmd.user_broker_account_id) == 9999


def test_user_own_uba_keeps_owner_user_id() -> None:
    """USER가 자기 UBA로 주문해도 user_id=owner 유지."""

    captured: dict = {}
    owner = AuthenticatedUser(
        user_id=61,
        username="owner61",
        roles=["user"],
        permissions=["trading:write"],
    )

    def _fake_submit(self, command):  # noqa: ANN001
        captured["command"] = command
        return OrderExecutionResult(
            allowed=True,
            reason_code="OK",
            order_id=3,
            outbox_id=3,
            status_code="PENDING",
            client_order_id="cid-3",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            position_plan=None,
        )

    with (
        patch(
            "stock_platform.api.v1.order_execution.assert_paper_account_access",
            return_value=SimpleNamespace(account_id=1),
        ),
        patch(
            "stock_platform.api.v1.order_execution.assert_active_broker_account_for_trading",
            return_value=_owner_uba(uba_id=1381, owner_user_id=61),
        ),
        patch(
            "stock_platform.api.v1.order_execution.require_live_broker_account_id",
            return_value=None,
        ),
        patch(
            "stock_platform.api.v1.order_execution.enforce_rate_limit",
            return_value=None,
        ),
        patch(
            "stock_platform.order.execution_service.OrderExecutionService.submit",
            _fake_submit,
        ),
    ):
        submit_order(
            _req(),
            MagicMock(),
            user=owner,
            session=MagicMock(),
        )

    cmd = captured["command"]
    assert int(cmd.user_id) == 61
    assert int(cmd.owner_user_id) == 61


def test_unauthorized_uba_still_blocked() -> None:
    with (
        patch(
            "stock_platform.api.v1.order_execution.assert_paper_account_access",
            return_value=SimpleNamespace(account_id=1),
        ),
        patch(
            "stock_platform.api.v1.order_execution.assert_active_broker_account_for_trading",
            side_effect=HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="해당 Broker 계좌에 대한 권한이 없습니다.",
            ),
        ),
        patch(
            "stock_platform.api.v1.order_execution.require_live_broker_account_id",
            return_value=None,
        ),
        patch(
            "stock_platform.api.v1.order_execution.enforce_rate_limit",
            return_value=None,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            submit_order(
                _req(),
                MagicMock(),
                user=_admin(),
                session=MagicMock(),
            )
    assert exc.value.status_code == 403
