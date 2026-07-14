from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.backtest.rebalancing_models import (
    RebalancingAsset,
    RebalancingFrequency,
)
from stock_platform.backtest.rebalancing_service import (
    PortfolioRebalancingBacktestService,
)


class FakePriceService:
    def get_between(self, **kwargs):
        start = kwargs["start_date"]
        symbol = kwargs["symbol"]

        values = (
            [100, 105, 110, 115]
            if symbol == "AAA"
            else [100, 98, 96, 94]
        )

        return [
            SimpleNamespace(
                trade_date=start + timedelta(days=index * 31),
                close_price=Decimal(str(value)),
            )
            for index, value in enumerate(values)
        ]


def test_monthly_rebalancing_backtest() -> None:
    service = PortfolioRebalancingBacktestService.__new__(
        PortfolioRebalancingBacktestService
    )
    service._price_service = FakePriceService()

    result = service.run(
        assets=[
            RebalancingAsset(
                exchange_code="KRX",
                symbol="AAA",
                target_weight=Decimal("0.50"),
            ),
            RebalancingAsset(
                exchange_code="KRX",
                symbol="BBB",
                target_weight=Decimal("0.50"),
            ),
        ],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 4, 30),
        initial_capital=Decimal("1000000"),
        frequency=RebalancingFrequency.MONTHLY,
        fee_ratio=Decimal("0"),
        sell_tax_ratio=Decimal("0"),
        slippage_ratio=Decimal("0"),
    )

    assert result.summary.initial_capital == Decimal(
        "1000000"
    )
    assert result.summary.final_equity > 0
    assert result.summary.rebalance_count == 4
    assert len(result.snapshots) == 4
    assert len(result.final_weights) == 2


def test_rebalance_frequency_detection() -> None:
    service = PortfolioRebalancingBacktestService

    assert service._is_rebalance_date(
        previous=date(2026, 1, 31),
        current=date(2026, 2, 1),
        frequency=RebalancingFrequency.MONTHLY,
    )

    assert not service._is_rebalance_date(
        previous=date(2026, 2, 1),
        current=date(2026, 2, 15),
        frequency=RebalancingFrequency.MONTHLY,
    )


def test_total_weight_cannot_exceed_one() -> None:
    try:
        PortfolioRebalancingBacktestService._validate(
            assets=[
                RebalancingAsset(
                    exchange_code="KRX",
                    symbol="AAA",
                    target_weight=Decimal("0.70"),
                ),
                RebalancingAsset(
                    exchange_code="KRX",
                    symbol="BBB",
                    target_weight=Decimal("0.40"),
                ),
            ],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            initial_capital=Decimal("1000000"),
            fee_ratio=Decimal("0"),
            sell_tax_ratio=Decimal("0"),
            slippage_ratio=Decimal("0"),
            rebalance_threshold=Decimal("0"),
        )
    except ValueError as exc:
        assert "total target weight" in str(exc)
    else:
        raise AssertionError("ValueError was not raised")
