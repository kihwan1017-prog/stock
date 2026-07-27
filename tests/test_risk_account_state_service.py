from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.risk_engine.account_state_service import (
    RiskAccountStateService,
)
from stock_platform.trading.account_identity import AccountIdentityError


def test_builds_risk_account_state_by_uba(monkeypatch) -> None:
    service = RiskAccountStateService(MagicMock())

    account = SimpleNamespace(
        deposit_amount=Decimal("1000000"),
        available_order_amount=Decimal("800000"),
        total_profit_loss=Decimal("10000"),
    )
    positions = [
        SimpleNamespace(
            exchange_code="KRX",
            symbol="005930",
            quantity=Decimal("10"),
            evaluation_amount=Decimal("720000"),
            profit_loss=Decimal("20000"),
        ),
        SimpleNamespace(
            exchange_code="KRX",
            symbol="000660",
            quantity=Decimal("5"),
            evaluation_amount=Decimal("900000"),
            profit_loss=Decimal("-10000"),
        ),
    ]

    class FakeRepo:
        def __init__(self, session):
            pass

        def get_active_by_uba(self, uba_id):
            assert uba_id == 42
            return account, positions

    monkeypatch.setattr(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository",
        FakeRepo,
    )

    state = service.load_by_uba(
        user_broker_account_id=42,
        exchange_code="KRX",
        symbol="005930",
    )

    assert state.cash_balance == Decimal("800000")
    assert state.invested_amount == Decimal("1620000")
    assert state.total_asset_value == Decimal("2620000")
    assert state.open_position_count == 2
    assert state.symbol_position_quantity == Decimal("10")


def test_legacy_load_raises() -> None:
    service = RiskAccountStateService(MagicMock())
    with pytest.raises(AccountIdentityError):
        service.load(
            broker_code="KIWOOM",
            account_number="123",
            exchange_code="KRX",
            symbol="005930",
        )
