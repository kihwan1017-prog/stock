"""STEP 8-3 — 전략 소유권·접근·시장 호환 단위 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.strategy_deployment.ownership import (
    StrategyDefinitionService,
    StrategyOwnershipError,
    assert_strategy_readable,
    assert_strategy_writable,
    market_compatible,
)
from stock_platform.strategy_deployment.runtime_models import (
    build_runtime_scope_key,
)


def _user(*, user_id: int, is_admin: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        username=f"user{user_id}",
        roles=["admin"] if is_admin else ["user"],
        permissions=["trading:read", "trading:write"],
    )


def _strategy(**kwargs):
    defaults = {
        "strategy_id": 1,
        "owner_type": "USER",
        "user_id": 10,
        "visibility": "PRIVATE",
        "is_active": True,
        "deleted_at": None,
        "approved_at": None,
        "market_type": "STOCK",
        "parameter_payload": {},
        "strategy_code": "S1",
        "name": "S1",
        "description": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_market_compatible_stock_crypto() -> None:
    assert market_compatible(market_type="STOCK", account_broker="KIWOOM")
    assert market_compatible(market_type="STOCK", account_broker="PAPER")
    assert not market_compatible(
        market_type="STOCK", account_broker="UPBIT"
    )
    assert market_compatible(market_type="CRYPTO", account_broker="UPBIT")
    assert market_compatible(
        market_type="CRYPTO", account_broker="PAPER_CRYPTO"
    )
    assert not market_compatible(
        market_type="CRYPTO", account_broker="KIWOOM"
    )


def test_readable_own_or_public() -> None:
    me = _user(user_id=10)
    other = _user(user_id=20)
    own = _strategy(user_id=10, visibility="PRIVATE")
    pub = _strategy(
        owner_type="SYSTEM",
        user_id=None,
        visibility="PUBLIC",
    )
    private_other = _strategy(user_id=20, visibility="PRIVATE")

    assert_strategy_readable(me, own)
    assert_strategy_readable(me, pub)
    with pytest.raises(HTTPException) as exc:
        assert_strategy_readable(me, private_other)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException):
        assert_strategy_readable(other, own)


def test_writable_blocks_public_and_system() -> None:
    me = _user(user_id=10)
    own = _strategy(user_id=10, visibility="PRIVATE")
    public_own = _strategy(user_id=10, visibility="PUBLIC")
    system = _strategy(
        owner_type="SYSTEM", user_id=None, visibility="PUBLIC"
    )

    assert_strategy_writable(me, own)
    with pytest.raises(HTTPException):
        assert_strategy_writable(me, public_own)
    with pytest.raises(HTTPException):
        assert_strategy_writable(me, system)


def test_create_user_strategy_forces_private_owner() -> None:
    session = MagicMock()
    service = StrategyDefinitionService(session)
    user = _user(user_id=7)
    row = service.create_user_strategy(
        user,
        strategy_code="MY_S",
        name="mine",
        description=None,
        market_type="STOCK",
        parameter_payload={"a": 1},
        actor="user7",
    )
    assert row.owner_type == "USER"
    assert row.user_id == 7
    assert row.visibility == "PRIVATE"
    assert row.is_active is False
    session.add.assert_called()


def test_clone_clears_approval_meta() -> None:
    session = MagicMock()
    source = _strategy(
        strategy_id=5,
        owner_type="SYSTEM",
        user_id=None,
        visibility="PUBLIC",
        strategy_code="SYS",
        name="Sys",
        approved_by="operator",
        approved_at=datetime.now(timezone.utc),
        published_by="operator",
        published_at=datetime.now(timezone.utc),
        parameter_payload={"fast": 5},
    )
    session.get.return_value = source
    service = StrategyDefinitionService(session)
    clone = service.clone_strategy(
        _user(user_id=3), 5, actor="user3", name="copy"
    )
    assert clone.owner_type == "USER"
    assert clone.user_id == 3
    assert clone.visibility == "PRIVATE"
    assert clone.approved_by is None
    assert clone.approved_at is None
    assert clone.published_by is None
    assert clone.published_at is None
    assert clone.parameter_payload == {"fast": 5}
    assert clone.source_strategy_id == 5


def test_runtime_scope_keys_isolated() -> None:
    a = build_runtime_scope_key(
        user_id=1,
        account_id=10,
        user_broker_account_id=None,
        strategy_id=100,
        strategy_code="PUB",
        market_code="KRX",
    )
    b = build_runtime_scope_key(
        user_id=2,
        account_id=20,
        user_broker_account_id=None,
        strategy_id=100,
        strategy_code="PUB",
        market_code="KRX",
    )
    assert a != b
    assert "user:1" in a
    assert "user:2" in b


def test_soft_delete_blocked_when_active_link() -> None:
    session = MagicMock()
    row = _strategy(strategy_id=9, user_id=1, visibility="PRIVATE")
    session.get.return_value = row
    session.scalar.return_value = SimpleNamespace(
        account_strategy_link_id=1
    )
    service = StrategyDefinitionService(session)
    with pytest.raises(StrategyOwnershipError):
        service.soft_delete_user_strategy(
            _user(user_id=1), 9, actor="u1"
        )
