from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.backtest.repository import BacktestRepository
from stock_platform.backtest.service import BacktestService


class BacktestPersistenceService:
    """백테스트 실행과 결과 저장을 연결한다."""

    def __init__(self, session: Session) -> None:
        self._backtest_service = BacktestService(session)
        self._repository = BacktestRepository(session)

    def run_and_save_moving_average(
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
        result = (
            self._backtest_service
            .run_moving_average_backtest(
                exchange_code=exchange_code,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                short_window=short_window,
                long_window=long_window,
                stop_loss_ratio=stop_loss_ratio,
                take_profit_ratio=take_profit_ratio,
                position_ratio=position_ratio,
                fee_ratio=fee_ratio,
                sell_tax_ratio=sell_tax_ratio,
                slippage_ratio=slippage_ratio,
            )
        )

        parameters = {
            "short_window": short_window,
            "long_window": long_window,
            "stop_loss_ratio": str(stop_loss_ratio),
            "take_profit_ratio": str(take_profit_ratio),
            "position_ratio": str(position_ratio),
            "fee_ratio": str(fee_ratio),
            "sell_tax_ratio": str(sell_tax_ratio),
            "slippage_ratio": str(slippage_ratio),
        }

        run = self._repository.save_result(
            result=result,
            strategy_code="MOVING_AVERAGE_CROSS",
            parameters=parameters,
        )

        return run, result
