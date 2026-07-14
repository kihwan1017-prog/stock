from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.trading.models import (
    OrderSide,
    OrderStatus,
    OrderType,
)
from stock_platform.trading.simulation_models import (
    SimulationRequest,
)
from stock_platform.trading.simulation_service import (
    DailyCloseFillSimulator,
)


class FakeOrderRepository:
    def __init__(self):
        self.order = SimpleNamespace(
            order_id=1,
            exchange_code="KRX",
            symbol="005930",
            side=OrderSide.BUY.value,
            order_type=OrderType.LIMIT.value,
            status_code=OrderStatus.ACCEPTED.value,
            requested_quantity=Decimal("10"),
            requested_price=Decimal("70000"),
            filled_quantity=Decimal("0"),
        )

    def get(self, order_id: int):
        return self.order if order_id == 1 else None

    def list_recent(self, **kwargs):
        return [self.order]


class FakePriceService:
    def get_between(self, **kwargs):
        return [
            SimpleNamespace(
                close_price=Decimal("69000")
            )
        ]


class FakeExecutionService:
    def apply_fill(self, **kwargs):
        return SimpleNamespace(
            order_status="FILLED",
            trade_id=10,
        )


def test_limit_buy_fills_when_close_is_below_limit() -> None:
    simulator = DailyCloseFillSimulator.__new__(
        DailyCloseFillSimulator
    )
    simulator._order_repository = FakeOrderRepository()
    simulator._price_service = FakePriceService()
    simulator._execution_service = FakeExecutionService()

    result = simulator.simulate_order(
        order_id=1,
        request=SimulationRequest(
            account_id=1,
            exchange_code="KRX",
            symbol="005930",
            trade_date=date(2026, 7, 13),
            slippage_ratio=Decimal("0.001"),
            fill_ratio=Decimal("1"),
        ),
    )

    assert result.fill_quantity == Decimal(
        "10.00000000"
    )
    assert result.reference_price == Decimal("69000")
    assert result.simulated_fill_price == Decimal(
        "69069.00000000"
    )
    assert result.order_status == "FILLED"


def test_partial_fill_ratio() -> None:
    simulator = DailyCloseFillSimulator.__new__(
        DailyCloseFillSimulator
    )
    simulator._order_repository = FakeOrderRepository()
    simulator._price_service = FakePriceService()
    simulator._execution_service = FakeExecutionService()

    result = simulator.simulate_order(
        order_id=1,
        request=SimulationRequest(
            account_id=1,
            exchange_code="KRX",
            symbol="005930",
            trade_date=date(2026, 7, 13),
            fill_ratio=Decimal("0.5"),
        ),
    )

    assert result.fill_quantity == Decimal(
        "5.00000000"
    )
