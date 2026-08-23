"""Strategy-owned binding fill idempotency — BUY qty SET, SELL close after inflate heal."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.risk_engine.strategy_owned_entities import (
    BINDING_STATUS_CLOSED,
    BINDING_STATUS_OPEN,
    StrategyPositionBindingEntity,
)
from stock_platform.risk_engine.strategy_owned_risk_service import (
    StrategyOwnedRiskService,
)


def _svc_with_rows(rows: list) -> tuple[StrategyOwnedRiskService, MagicMock]:
    session = MagicMock()
    session.scalar = MagicMock(
        side_effect=lambda *_a, **_k: rows[0] if rows else None
    )

    def _scalars(stmt):  # noqa: ARG001
        result = MagicMock()
        result.__iter__ = lambda self: iter(list(rows))
        # list(session.scalars(...)) uses __iter__
        return iter(list(rows))

    session.scalars = MagicMock(side_effect=_scalars)
    session.get = MagicMock(return_value=None)
    session.add = MagicMock(side_effect=lambda r: rows.append(r))
    session.flush = MagicMock()
    return StrategyOwnedRiskService(session), session


def test_buy_fill_resync_does_not_inflate_qty() -> None:
    rows: list = []
    svc, session = _svc_with_rows(rows)

    created = StrategyPositionBindingEntity(
        binding_id=1,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        symbol="KRW-TEST",
        status=BINDING_STATUS_OPEN,
        ownership_code="STRATEGY_OWNED",
        entry_order_id=100,
        owned_quantity=Decimal("32.05"),
        entry_price=Decimal("312"),
        fees=Decimal("5"),
    )
    rows.append(created)
    # scalar finds existing
    session.scalar = MagicMock(return_value=created)

    kwargs = dict(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        deployment_id=None,
        symbol="KRW-TEST",
        entry_order_id=100,
        broker_order_id="b-1",
        quantity=Decimal("32.05"),
        entry_price=Decimal("312"),
        side="BUY",
        fees=Decimal("5"),
    )
    b2 = svc.ensure_binding_from_fill(**kwargs)
    assert b2 is created
    assert Decimal(str(created.owned_quantity)) == Decimal("32.05")


def test_sell_closes_after_inflated_qty_self_heal() -> None:
    buy = SimpleNamespace(
        order_id=200,
        filled_quantity=Decimal("32.05"),
        status_code="FILLED",
    )
    row = StrategyPositionBindingEntity(
        binding_id=10,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        symbol="KRW-TEST",
        status=BINDING_STATUS_OPEN,
        ownership_code="STRATEGY_OWNED",
        entry_order_id=200,
        owned_quantity=Decimal("110.09"),
        entry_price=Decimal("312"),
        fees=Decimal("5"),
        realized_pnl=Decimal("0"),
        opened_at=datetime.now(timezone.utc),
        meta_json={},
    )
    rows = [row]
    svc, session = _svc_with_rows(rows)
    # first scalars: prior exit lookup (empty match) — return all rows then opens
    calls = {"n": 0}

    def _scalars(_stmt):
        calls["n"] += 1
        # 1st call: prior by symbol (idempotency scan)
        # 2nd call: opens
        return iter(list(rows))

    session.scalars = MagicMock(side_effect=_scalars)
    session.get = MagicMock(return_value=buy)

    closed = svc.ensure_binding_from_fill(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        deployment_id=None,
        symbol="KRW-TEST",
        entry_order_id=None,
        broker_order_id="s-1",
        quantity=Decimal("32.05"),
        entry_price=None,
        side="SELL",
        fees=Decimal("5.03"),
        fill_price=Decimal("314"),
        exit_order_id=201,
        filled_at=datetime.now(timezone.utc),
    )
    assert closed is row
    assert row.status == BINDING_STATUS_CLOSED
    assert Decimal(str(row.owned_quantity)) == Decimal("0")
    assert int((row.meta_json or {}).get("exit_order_id")) == 201

    # duplicate sell — prior scan finds exit_order_id
    row.meta_json = {"exit_order_id": 201}
    again = svc.ensure_binding_from_fill(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=1,
        deployment_id=None,
        symbol="KRW-TEST",
        entry_order_id=None,
        broker_order_id="s-1",
        quantity=Decimal("32.05"),
        entry_price=None,
        side="SELL",
        fees=Decimal("5.03"),
        fill_price=Decimal("314"),
        exit_order_id=201,
        filled_at=datetime.now(timezone.utc),
    )
    assert again is row
    assert row.status == BINDING_STATUS_CLOSED
    assert Decimal(str(row.fees)) == Decimal("10.03")


def test_buy_does_not_reopen_closed_binding() -> None:
    closed = StrategyPositionBindingEntity(
        binding_id=9,
        user_broker_account_id=1,
        broker_code="UPBIT",
        strategy_id=1,
        symbol="KRW-X",
        status=BINDING_STATUS_CLOSED,
        ownership_code="STRATEGY_OWNED",
        entry_order_id=9,
        owned_quantity=Decimal("0"),
        entry_price=Decimal("10"),
        fees=Decimal("0.1"),
        closed_at=datetime.now(timezone.utc),
    )
    svc, session = _svc_with_rows([closed])
    session.scalar = MagicMock(return_value=closed)
    again = svc.ensure_binding_from_fill(
        user_broker_account_id=1,
        broker_code="UPBIT",
        strategy_id=1,
        deployment_id=None,
        symbol="KRW-X",
        entry_order_id=9,
        broker_order_id="b",
        quantity=Decimal("1"),
        entry_price=Decimal("10"),
        side="BUY",
        fees=Decimal("0.1"),
    )
    assert again is closed
    assert again.status == BINDING_STATUS_CLOSED
