"""주문·체결 전략 Provenance 단위 테스트."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from stock_platform.trading.models import OrderSide, OrderType
from stock_platform.trading.order_strategy_provenance import (
    UNATTRIBUTED,
    OrderStrategyProvenance,
    provenance_from_mapping,
    provenance_from_order_entity,
)
from stock_platform.trading.paper_engine import PaperOrderEngine


@pytest.mark.unit
def test_provenance_defaults_are_unattributed() -> None:
    prov = OrderStrategyProvenance()
    assert prov.attribution_label() == UNATTRIBUTED
    assert prov.as_column_kwargs()["strategy_id"] is None
    assert prov.as_column_kwargs()["execution_mode"] is None


@pytest.mark.unit
def test_provenance_from_mapping_and_entity() -> None:
    mapping = provenance_from_mapping(
        {
            "strategy_id": "42",
            "strategy_version": 3,
            "runtime_scope_hash": " abc ",
            "account_strategy_link_id": 7,
            "user_id": 9,
            "execution_mode": "paper",
        }
    )
    assert mapping.strategy_id == 42
    assert mapping.strategy_version == 3
    assert mapping.runtime_scope_hash == "abc"
    assert mapping.execution_mode == "PAPER"
    assert mapping.attribution_label() == "strategy:42"

    entity = provenance_from_order_entity(
        SimpleNamespace(
            strategy_id=42,
            strategy_version=3,
            runtime_scope_hash="abc",
            account_strategy_link_id=7,
            user_id=9,
            execution_mode="PAPER",
        )
    )
    assert entity.as_column_kwargs() == mapping.as_column_kwargs()


@pytest.mark.unit
def test_empty_mapping_stays_null_not_invented() -> None:
    assert provenance_from_mapping(None).strategy_id is None
    assert provenance_from_mapping({}).strategy_id is None


@pytest.mark.unit
def test_paper_order_engine_preserves_provenance() -> None:
    engine = PaperOrderEngine()
    order = engine.create_order(
        account_id=1,
        exchange_code="KRX",
        symbol="005930",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        price=None,
        provenance=OrderStrategyProvenance(
            strategy_id=100,
            strategy_version=2,
            runtime_scope_hash="scope-hash",
            account_strategy_link_id=5,
            user_id=11,
            execution_mode="PAPER",
        ),
    )
    assert order.strategy_id == 100
    assert order.strategy_version == 2
    assert order.runtime_scope_hash == "scope-hash"
    assert order.account_strategy_link_id == 5
    assert order.user_id == 11
    assert order.execution_mode == "PAPER"


@pytest.mark.unit
def test_paper_order_without_provenance_leaves_null() -> None:
    order = PaperOrderEngine().create_order(
        account_id=1,
        exchange_code="KRX",
        symbol="005930",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        price=None,
    )
    assert order.strategy_id is None
    assert order.execution_mode is None
