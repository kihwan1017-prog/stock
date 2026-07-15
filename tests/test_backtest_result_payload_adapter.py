from datetime import date
from decimal import Decimal

from stock_platform.performance.backtest_result_adapter import (
    BacktestResultPayloadAdapter,
)


def test_accepts_common_aliases() -> None:
    source = BacktestResultPayloadAdapter.from_payload(
        strategy_code="RSI_V1",
        market_code="UPBIT",
        symbol="KRW-BTC",
        period_start_date=date(2024, 1, 1),
        period_end_date=date(2024, 12, 31),
        parameter_payload={"rsi": 14},
        result_payload={
            "starting_capital": "10000000",
            "ending_capital": "10500000",
            "total_trades": 8,
            "winning_trades": 5,
            "losing_trades": 3,
            "gross_profit": "900000",
            "gross_loss": "-400000",
            "mdd": "0.07",
            "sharpe": "1.1",
        },
    )

    assert source.initial_capital == Decimal(
        "10000000"
    )
    assert source.final_capital == Decimal(
        "10500000"
    )
    assert source.total_trade_count == 8
    assert source.sharpe_ratio == Decimal("1.1")
