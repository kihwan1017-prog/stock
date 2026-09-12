"""UPBIT MA Strategy 구축 — focused tests (실주문 0)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.realtime.hub_constants import SignalType
from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
from stock_platform.realtime.market_event import RealtimeMarketEvent
from stock_platform.realtime.runtime_bridge import _config_from_entry
from stock_platform.realtime.strategy_models import (
    RealtimePositionState,
    RealtimeStrategyConfig,
)
from stock_platform.strategy_deployment.ownership import (
    StrategyDefinitionService,
    StrategyOwnershipError,
    market_compatible,
)
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    StrategyRuntimeScope,
)


def _user(user_id: int = 61, *, admin: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        username=f"u{user_id}",
        roles=["admin"] if admin else ["user"],
        permissions=["trading:read", "trading:write"],
    )


def _scope(strategy_id: int = 9) -> StrategyRuntimeScope:
    return StrategyRuntimeScope(
        user_id=61,
        account_kind=AccountKind.USER_BROKER,
        account_id=1380,
        strategy_id=strategy_id,
        strategy_version="1",
        broker_code="UPBIT",
        market_type="CRYPTO",
    )


def _event(price: str, seq: int) -> RealtimeMarketEvent:
    now = datetime.now(timezone.utc)
    return RealtimeMarketEvent(
        broker_code="UPBIT",
        market_type="CRYPTO",
        symbol="KRW-XRP",
        event_type="TICKER",
        event_time=now,
        received_at=now,
        exchange_code="UPBIT",
        price=Decimal(price),
        change_rate=Decimal("0.01"),
        raw_sequence=seq,
    )


def test_upbit_crypto_market_compatible() -> None:
    assert market_compatible(market_type="CRYPTO", account_broker="UPBIT")
    assert not market_compatible(
        market_type="STOCK", account_broker="UPBIT"
    )


def test_runtime_bridge_parses_ma_payload() -> None:
    entry = SimpleNamespace(
        runtime=SimpleNamespace(
            parameter_payload={
                "short_window": 5,
                "long_window": 20,
                "stop_loss_ratio": "0.03",
                "take_profit_ratio": "0.06",
                "cooldown_seconds": 10,
            }
        )
    )
    cfg = _config_from_entry(entry)
    assert cfg.short_window == 5
    assert cfg.long_window == 20
    assert cfg.stop_loss_ratio == Decimal("0.03")
    assert cfg.take_profit_ratio == Decimal("0.06")
    assert cfg.timeframe == ""
    assert cfg.cooldown_bars is None


def test_ma_evaluator_emits_buy_and_sell() -> None:
    ev = MovingAverageStrategyEvaluator(
        _scope(),
        RealtimeStrategyConfig(
            short_window=3,
            long_window=5,
            cooldown_seconds=0,
            minimum_change_rate=Decimal("0"),
        ),
    )
    prices = [
        "100",
        "100",
        "100",
        "100",
        "100",
        "101",
        "103",
        "108",
        "115",
        "120",
        "118",
        "110",
        "100",
        "90",
    ]
    position = RealtimePositionState(
        quantity=Decimal("0"), average_entry_price=None
    )
    types: list[str] = []
    for i, p in enumerate(prices):
        sig = ev.evaluate(
            _event(p, i + 1), position=position, allow_signal=True
        )
        if sig is None:
            continue
        types.append(str(sig.signal_type))
        if sig.signal_type == SignalType.BUY:
            position = RealtimePositionState(
                quantity=Decimal("1"), average_entry_price=Decimal(p)
            )
        elif sig.signal_type == SignalType.SELL:
            position = RealtimePositionState(
                quantity=Decimal("0"), average_entry_price=None
            )
    assert "BUY" in types
    assert "SELL" in types


def test_inactive_strategy_link_blocked() -> None:
    session = MagicMock()
    strategy = SimpleNamespace(
        strategy_id=9,
        is_active=False,
        deleted_at=None,
        approved_at=datetime.now(timezone.utc),
        visibility="PRIVATE",
        owner_type="USER",
        user_id=61,
        market_type="CRYPTO",
    )
    service = StrategyDefinitionService(session)
    service.require = MagicMock(return_value=strategy)  # type: ignore[method-assign]
    with pytest.raises(StrategyOwnershipError, match="비활성"):
        service.link_to_account(
            _user(),
            strategy_id=9,
            paper_account_id=None,
            user_broker_account_id=1380,
            account_broker="UPBIT",
            actor="t",
        )


def test_create_user_strategy_defaults_inactive() -> None:
    session = MagicMock()
    added = []

    def _add(obj):
        added.append(obj)

    session.add.side_effect = _add
    service = StrategyDefinitionService(session)
    row = service.create_user_strategy(
        _user(),
        strategy_code="UPBIT_MA_TEST",
        name="MA",
        description=None,
        market_type="CRYPTO",
        parameter_payload={
            "short_window": 5,
            "long_window": 20,
            "symbol": "KRW-XRP",
        },
        actor="t",
    )
    assert row.is_active is False
    assert row.market_type == "CRYPTO"
    assert row.owner_type == "USER"
    assert row.user_id == 61
    assert added
