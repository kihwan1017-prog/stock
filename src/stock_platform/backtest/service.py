from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.backtest.engine import BacktestEngine
from stock_platform.backtest.models import BacktestPrice
from stock_platform.backtest.strategy import (
    MovingAverageCrossStrategy,
    MovingAverageStrategyConfig,
)
from stock_platform.markets.repository import PriceDailyRepository
from stock_platform.markets.service import PriceDailyService


class BacktestService:
    def __init__(self, session: Session) -> None:
        self._price_service = PriceDailyService(
            PriceDailyRepository(session)
        )

    def run_moving_average_backtest(
        self,
        *,
        exchange_code: str,
        symbol: str,
        start_date: date,
        end_date: date,
        initial_capital: Decimal,
        short_window: int,
        long_window: int,
        stop_loss_ratio: Decimal,
        take_profit_ratio: Decimal,
        position_ratio: Decimal,
        fee_ratio: Decimal,
        sell_tax_ratio: Decimal,
        slippage_ratio: Decimal,
    ):
        rows = self._price_service.get_between(
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
            start_date=start_date,
            end_date=end_date,
        )

        prices = [
            BacktestPrice(
                trade_date=row.trade_date,
                open_price=Decimal(row.open_price),
                high_price=Decimal(row.high_price),
                low_price=Decimal(row.low_price),
                close_price=Decimal(row.close_price),
                volume=Decimal(row.volume),
            )
            for row in rows
        ]

        strategy = MovingAverageCrossStrategy(
            MovingAverageStrategyConfig(
                short_window=short_window,
                long_window=long_window,
                stop_loss_ratio=stop_loss_ratio,
                take_profit_ratio=take_profit_ratio,
                position_ratio=position_ratio,
            )
        )

        return BacktestEngine(strategy).run(
            exchange_code=exchange_code,
            symbol=symbol,
            prices=prices,
            initial_capital=initial_capital,
            fee_ratio=fee_ratio,
            sell_tax_ratio=sell_tax_ratio,
            slippage_ratio=slippage_ratio,
        )
