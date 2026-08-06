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
        total_profit_loss=Decimal("-999999"),  # 누적손익 — 무시해야 함
        user_broker_account_id=42,
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

    class FakeDaily:
        def __init__(self, session):
            pass

        def diagnose(self, *, user_broker_account_id, loss_limit):
            assert user_broker_account_id == 42
            return SimpleNamespace(
                current_daily_pnl=Decimal("-1500"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("-1500"),
            )

    monkeypatch.setattr(
        "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository",
        FakeRepo,
    )
    monkeypatch.setattr(
        "stock_platform.risk_engine.uba_daily_loss_service.UbaDailyLossService",
        FakeDaily,
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
    # 당일 손익만 — 누적 -999999 사용 금지
    assert state.daily_realized_profit_loss == Decimal("-1500")
    assert state.daily_unrealized_profit_loss == Decimal("0")


def test_legacy_load_raises() -> None:
    service = RiskAccountStateService(MagicMock())
    with pytest.raises(AccountIdentityError):
        service.load(
            broker_code="KIWOOM",
            account_number="123",
            exchange_code="KRX",
            symbol="005930",
        )
