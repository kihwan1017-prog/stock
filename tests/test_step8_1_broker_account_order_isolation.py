"""STEP 8-1 — UserBrokerAccount 단위 주문 격리 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from stock_platform.auth.account_ownership import (
    assert_active_broker_account_for_trading,
    assert_broker_account_access,
    assert_order_resource_access,
    require_live_broker_account_id,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.auth.role_codes import normalize_role_codes
from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderSide,
    BrokerOrderType,
)
from stock_platform.broker.order_account_context import (
    require_user_broker_context_for_live,
)
from stock_platform.order.outbox_dispatcher import OrderOutboxDispatcher


def _user(user_id: int, *, admin: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        username=f"user{user_id}",
        roles=["admin"] if admin else ["user"],
        permissions=["trading:read", "trading:write"],
    )


def _order(
    *,
    account_id: int = 1,
    user_broker_account_id: int | None = None,
) -> MagicMock:
    order = MagicMock()
    order.account_id = account_id
    order.user_broker_account_id = user_broker_account_id
    return order


def test_require_live_broker_account_id_blocks_missing_uba() -> None:
    with pytest.raises(HTTPException) as exc:
        require_live_broker_account_id(
            environment="LIVE",
            broker_code="KIWOOM",
            user_broker_account_id=None,
        )
    assert exc.value.status_code == 400


def test_require_live_broker_account_id_allows_paper() -> None:
    require_live_broker_account_id(
        environment="PAPER",
        broker_code="KIWOOM",
        user_broker_account_id=None,
    )


def test_assert_order_resource_access_uses_uba_owner() -> None:
    session = MagicMock()
    uba = MagicMock()
    uba.user_id = 10
    session.get.return_value = uba

    assert_order_resource_access(
        _user(10),
        _order(user_broker_account_id=55),
        session,
    )
    with pytest.raises(HTTPException) as exc:
        assert_order_resource_access(
            _user(99),
            _order(user_broker_account_id=55),
            session,
        )
    assert exc.value.status_code == 403


def test_assert_order_resource_access_falls_back_to_paper() -> None:
    session = MagicMock()
    paper = MagicMock()
    paper.user_id = 7
    with pytest.MonkeyPatch.context() as mp:
        repo = MagicMock()
        repo.get_account.return_value = paper
        mp.setattr(
            "stock_platform.auth.account_ownership.PaperAccountRepository",
            lambda _session: repo,
        )
        assert_order_resource_access(
            _user(7),
            _order(account_id=3, user_broker_account_id=None),
            session,
        )
        with pytest.raises(HTTPException) as exc:
            assert_order_resource_access(
                _user(8),
                _order(account_id=3, user_broker_account_id=None),
                session,
            )
        assert exc.value.status_code == 403


def test_inactive_broker_account_blocks_new_order() -> None:
    session = MagicMock()
    row = MagicMock()
    row.user_id = 1
    row.is_active = False
    row.broker_code = "KIWOOM"
    session.get.return_value = row
    with pytest.raises(HTTPException) as exc:
        assert_active_broker_account_for_trading(
            _user(1), 9, session, expected_broker_code="KIWOOM"
        )
    assert exc.value.status_code == 403


def test_deleted_like_inactive_broker_account_blocks_new_order() -> None:
    # UBA는 deleted_at 없음 — is_active=False 를 삭제로 취급
    session = MagicMock()
    row = MagicMock()
    row.user_id = 1
    row.is_active = False
    row.broker_code = "UPBIT"
    session.get.return_value = row
    with pytest.raises(HTTPException) as exc:
        assert_active_broker_account_for_trading(
            _user(1), 11, session, expected_broker_code="UPBIT"
        )
    assert exc.value.status_code == 403


def test_user_a_cannot_use_user_b_broker_account() -> None:
    session = MagicMock()
    row = MagicMock()
    row.user_id = 2
    session.get.return_value = row
    with pytest.raises(HTTPException) as exc:
        assert_broker_account_access(_user(1), 100, session)
    assert exc.value.status_code == 403


def test_admin_can_access_any_broker_account() -> None:
    session = MagicMock()
    row = MagicMock()
    row.user_id = 2
    row.is_active = True
    row.broker_code = "KIWOOM"
    session.get.return_value = row
    result = assert_active_broker_account_for_trading(
        _user(99, admin=True),
        100,
        session,
        expected_broker_code="KIWOOM",
    )
    assert result is row


def test_jwt_role_spoof_viewer_cannot_bypass_ownership() -> None:
    # JWT claim 에 viewer/trading:write 를 넣어도 소유권은 user_id 로 차단
    forged = AuthenticatedUser(
        user_id=1,
        username="forged",
        roles=["viewer"],
        permissions=["trading:write"],
    )
    assert "admin" not in normalize_role_codes(list(forged.roles))
    session = MagicMock()
    row = MagicMock()
    row.user_id = 2
    session.get.return_value = row
    with pytest.raises(HTTPException) as exc:
        assert_order_resource_access(
            forged,
            _order(user_broker_account_id=1),
            session,
        )
    assert exc.value.status_code == 403



def test_adapter_rejects_live_without_uba() -> None:
    request = BrokerOrderRequest(
        client_order_id="C1",
        exchange_code="KRX",
        symbol="005930",
        side=BrokerOrderSide.BUY,
        order_type=BrokerOrderType.LIMIT,
        quantity=__import__("decimal").Decimal("1"),
        price=__import__("decimal").Decimal("70000"),
        account_type="LIVE",
        broker_code="KIWOOM",
        user_broker_account_id=None,
    )
    with pytest.raises(PermissionError):
        require_user_broker_context_for_live(request)


def test_adapter_allows_live_with_uba() -> None:
    request = BrokerOrderRequest(
        client_order_id="C1",
        exchange_code="KRW",
        symbol="BTC",
        side=BrokerOrderSide.BUY,
        order_type=BrokerOrderType.LIMIT,
        quantity=__import__("decimal").Decimal("1"),
        price=__import__("decimal").Decimal("100"),
        account_type="LIVE",
        broker_code="UPBIT",
        user_broker_account_id=12,
        owner_user_id=3,
        uses_system_shared_credential=True,
        credential_ref="SYSTEM_SHARED:UPBIT",
    )
    require_user_broker_context_for_live(request)


def test_outbox_payload_maps_uba_fields() -> None:
    req = OrderOutboxDispatcher._to_order_request(
        {
            "client_order_id": "CID-1",
            "account_id": 10,
            "user_broker_account_id": 77,
            "broker_code": "KIWOOM",
            "environment": "LIVE",
            "account_type": "LIVE",
            "external_account_ref": "******7890",
            "owner_user_id": 5,
            "uses_system_shared_credential": True,
            "credential_ref": "SYSTEM_SHARED:KIWOOM",
            "exchange_code": "KRX",
            "symbol": "005930",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": "1",
            "price": "70000",
            "time_in_force": "DAY",
        }
    )
    assert req.user_broker_account_id == 77
    assert req.broker_code == "KIWOOM"
    assert req.account_type == "LIVE"
    assert req.owner_user_id == 5
    assert req.uses_system_shared_credential is True
    assert req.external_account_ref == "******7890"


def test_same_broker_order_id_can_differ_by_uba_lookup_signature() -> None:
    # repository 시그니처가 user_broker_account_id 를 받는지 확인
    from stock_platform.order.repository import TradingOrderRepository
    import inspect

    params = inspect.signature(
        TradingOrderRepository.get_by_broker_order_id
    ).parameters
    assert "user_broker_account_id" in params


def test_paper_create_order_command_uba_optional() -> None:
    from decimal import Decimal

    from stock_platform.order.models import (
        CreateOrderCommand,
        OrderSide,
        OrderType,
    )

    cmd = CreateOrderCommand(
        account_id=1,
        broker_code="PAPER",
        exchange_code="KRX",
        symbol="005930",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        price=Decimal("1000"),
    )
    assert cmd.user_broker_account_id is None
