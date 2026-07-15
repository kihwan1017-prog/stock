from __future__ import annotations

from decimal import Decimal

from stock_platform.performance.backtest_models import (
    BacktestPerformanceInput,
)
from stock_platform.performance.models import (
    StrategyPerformanceMetrics,
)


ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")


class BacktestPerformanceMapper:
    """
    기존 백테스트 결과를 공통 성과 지표 모델로 변환한다.

    수익률 계열은 소수 비율을 사용한다.
    예: 10% -> Decimal("0.10")
    """

    @classmethod
    def to_metrics(
        cls,
        source: BacktestPerformanceInput,
    ) -> StrategyPerformanceMetrics:
        if source.initial_capital <= ZERO:
            raise ValueError(
                "initial_capital must be greater than zero"
            )

        if source.final_capital < ZERO:
            raise ValueError(
                "final_capital must not be negative"
            )

        if source.total_trade_count < 0:
            raise ValueError(
                "total_trade_count must not be negative"
            )

        if (
            source.winning_trade_count
            + source.losing_trade_count
            > source.total_trade_count
        ):
            raise ValueError(
                "winning and losing trade count exceed total"
            )

        net_profit = (
            source.final_capital - source.initial_capital
        )
        total_return_rate = (
            net_profit / source.initial_capital
        )

        win_rate = (
            Decimal(source.winning_trade_count)
            / Decimal(source.total_trade_count)
            if source.total_trade_count > 0
            else ZERO
        )

        average_profit = (
            source.gross_profit_amount
            / Decimal(source.winning_trade_count)
            if source.winning_trade_count > 0
            else ZERO
        )

        average_loss = (
            source.gross_loss_amount
            / Decimal(source.losing_trade_count)
            if source.losing_trade_count > 0
            else ZERO
        )

        profit_factor = (
            source.profit_factor
            if source.profit_factor is not None
            else cls._profit_factor(
                gross_profit=source.gross_profit_amount,
                gross_loss=source.gross_loss_amount,
            )
        )

        return StrategyPerformanceMetrics(
            initial_capital=source.initial_capital,
            final_capital=source.final_capital,
            total_return_rate=total_return_rate,
            annualized_return_rate=(
                source.annualized_return_rate
            ),
            maximum_drawdown_rate=(
                source.maximum_drawdown_rate
            ),
            volatility_rate=source.volatility_rate,
            sharpe_ratio=source.sharpe_ratio,
            sortino_ratio=source.sortino_ratio,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trade_count=source.total_trade_count,
            winning_trade_count=(
                source.winning_trade_count
            ),
            losing_trade_count=(
                source.losing_trade_count
            ),
            average_profit_amount=average_profit,
            average_loss_amount=average_loss,
            gross_profit_amount=(
                source.gross_profit_amount
            ),
            gross_loss_amount=(
                source.gross_loss_amount
            ),
            net_profit_amount=net_profit,
        )

    @staticmethod
    def _profit_factor(
        *,
        gross_profit: Decimal,
        gross_loss: Decimal,
    ) -> Decimal | None:
        absolute_loss = abs(gross_loss)

        if absolute_loss == ZERO:
            return None

        return gross_profit / absolute_loss
