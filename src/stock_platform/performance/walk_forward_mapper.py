from __future__ import annotations

from decimal import Decimal
from statistics import mean, pstdev

from stock_platform.performance.backtest_mapper import (
    BacktestPerformanceMapper,
)
from stock_platform.performance.backtest_result_adapter import (
    BacktestResultPayloadAdapter,
)
from stock_platform.performance.models import (
    StrategyPerformanceMetrics,
)
from stock_platform.performance.walk_forward_entities import (
    WalkForwardWindowMetricEntity,
)
from stock_platform.performance.walk_forward_models import (
    WalkForwardPerformanceInput,
)


ZERO = Decimal("0")


class WalkForwardPerformanceMapper:
    @classmethod
    def to_window_entities(
        cls,
        source: WalkForwardPerformanceInput,
    ) -> list[WalkForwardWindowMetricEntity]:
        entities: list[WalkForwardWindowMetricEntity] = []

        for window in source.windows:
            backtest_input = (
                BacktestResultPayloadAdapter.from_payload(
                    strategy_code=source.strategy_code,
                    market_code=source.market_code,
                    symbol=source.symbol,
                    period_start_date=window.test_start_date,
                    period_end_date=window.test_end_date,
                    parameter_payload=window.parameter_payload,
                    result_payload=window.result_payload,
                )
            )
            metrics = BacktestPerformanceMapper.to_metrics(
                backtest_input
            )

            entities.append(
                WalkForwardWindowMetricEntity(
                    strategy_performance_run_id=0,
                    window_no=window.window_no,
                    train_start_date=window.train_start_date,
                    train_end_date=window.train_end_date,
                    test_start_date=window.test_start_date,
                    test_end_date=window.test_end_date,
                    initial_capital=metrics.initial_capital,
                    final_capital=metrics.final_capital,
                    total_return_rate=(
                        metrics.total_return_rate
                    ),
                    maximum_drawdown_rate=(
                        metrics.maximum_drawdown_rate
                    ),
                    sharpe_ratio=metrics.sharpe_ratio,
                    sortino_ratio=metrics.sortino_ratio,
                    win_rate=metrics.win_rate,
                    profit_factor=metrics.profit_factor,
                    total_trade_count=(
                        metrics.total_trade_count
                    ),
                    net_profit_amount=(
                        metrics.net_profit_amount
                    ),
                    parameter_payload=(
                        window.parameter_payload
                    ),
                    result_payload=window.result_payload,
                )
            )

        return entities

    @classmethod
    def aggregate_metrics(
        cls,
        windows: list[WalkForwardWindowMetricEntity],
    ) -> StrategyPerformanceMetrics:
        if not windows:
            raise ValueError(
                "Walk Forward windows must not be empty"
            )

        initial_capital = Decimal(
            windows[0].initial_capital
        )
        total_net_profit = sum(
            (
                Decimal(item.net_profit_amount)
                for item in windows
            ),
            ZERO,
        )
        final_capital = (
            initial_capital + total_net_profit
        )

        total_trade_count = sum(
            item.total_trade_count
            for item in windows
        )
        weighted_win_count = sum(
            (
                Decimal(item.win_rate)
                * Decimal(item.total_trade_count)
            )
            for item in windows
        )
        win_rate = (
            weighted_win_count
            / Decimal(total_trade_count)
            if total_trade_count > 0
            else ZERO
        )

        return_rates = [
            Decimal(item.total_return_rate)
            for item in windows
        ]
        average_return_rate = (
            sum(return_rates, ZERO)
            / Decimal(len(return_rates))
        )

        mdd = max(
            Decimal(item.maximum_drawdown_rate)
            for item in windows
        )

        sharpe_values = [
            Decimal(item.sharpe_ratio)
            for item in windows
            if item.sharpe_ratio is not None
        ]
        sortino_values = [
            Decimal(item.sortino_ratio)
            for item in windows
            if item.sortino_ratio is not None
        ]
        profit_factor_values = [
            Decimal(item.profit_factor)
            for item in windows
            if item.profit_factor is not None
        ]

        gross_profit = sum(
            (
                Decimal(
                    item.result_payload.get(
                        "gross_profit_amount",
                        item.result_payload.get(
                            "gross_profit",
                            0,
                        ),
                    )
                )
                for item in windows
            ),
            ZERO,
        )
        gross_loss = sum(
            (
                Decimal(
                    item.result_payload.get(
                        "gross_loss_amount",
                        item.result_payload.get(
                            "gross_loss",
                            0,
                        ),
                    )
                )
                for item in windows
            ),
            ZERO,
        )

        return StrategyPerformanceMetrics(
            initial_capital=initial_capital,
            final_capital=final_capital,
            total_return_rate=(
                total_net_profit / initial_capital
            ),
            annualized_return_rate=None,
            maximum_drawdown_rate=mdd,
            volatility_rate=(
                Decimal(str(pstdev(
                    [float(value) for value in return_rates]
                )))
                if len(return_rates) > 1
                else ZERO
            ),
            sharpe_ratio=(
                sum(sharpe_values, ZERO)
                / Decimal(len(sharpe_values))
                if sharpe_values
                else None
            ),
            sortino_ratio=(
                sum(sortino_values, ZERO)
                / Decimal(len(sortino_values))
                if sortino_values
                else None
            ),
            win_rate=win_rate,
            profit_factor=(
                sum(profit_factor_values, ZERO)
                / Decimal(len(profit_factor_values))
                if profit_factor_values
                else None
            ),
            total_trade_count=total_trade_count,
            winning_trade_count=0,
            losing_trade_count=0,
            average_profit_amount=ZERO,
            average_loss_amount=ZERO,
            gross_profit_amount=gross_profit,
            gross_loss_amount=gross_loss,
            net_profit_amount=total_net_profit,
        )
