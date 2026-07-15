from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.performance.entities import (
    StrategyPerformanceMetricEntity,
    StrategyPerformanceRunEntity,
)


class StrategyPerformanceSummaryService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def summarize(
        self,
        *,
        strategy_code: str | None = None,
        run_type: str | None = None,
        market_code: str | None = None,
    ) -> dict:
        statement = (
            select(
                func.count().label("run_count"),
                func.avg(
                    StrategyPerformanceMetricEntity
                    .total_return_rate
                ).label("average_return_rate"),
                func.avg(
                    StrategyPerformanceMetricEntity
                    .win_rate
                ).label("average_win_rate"),
                func.avg(
                    StrategyPerformanceMetricEntity
                    .maximum_drawdown_rate
                ).label("average_mdd"),
                func.avg(
                    StrategyPerformanceMetricEntity
                    .sharpe_ratio
                ).label("average_sharpe"),
                func.sum(
                    StrategyPerformanceMetricEntity
                    .net_profit_amount
                ).label("total_net_profit"),
                func.sum(
                    StrategyPerformanceMetricEntity
                    .total_trade_count
                ).label("total_trade_count"),
            )
            .join(
                StrategyPerformanceRunEntity,
                StrategyPerformanceRunEntity
                .strategy_performance_run_id
                == StrategyPerformanceMetricEntity
                .strategy_performance_run_id,
            )
            .where(
                StrategyPerformanceRunEntity.status_code
                == "COMPLETED"
            )
        )

        if strategy_code:
            statement = statement.where(
                StrategyPerformanceRunEntity.strategy_code
                == strategy_code
            )

        if run_type:
            statement = statement.where(
                StrategyPerformanceRunEntity.run_type
                == run_type.upper()
            )

        if market_code:
            statement = statement.where(
                StrategyPerformanceRunEntity.market_code
                == market_code.upper()
            )

        row = self._session.execute(
            statement
        ).one()

        return {
            "run_count": int(row.run_count or 0),
            "average_return_rate": self._text(
                row.average_return_rate
            ),
            "average_win_rate": self._text(
                row.average_win_rate
            ),
            "average_mdd": self._text(
                row.average_mdd
            ),
            "average_sharpe": self._text(
                row.average_sharpe
            ),
            "total_net_profit": self._text(
                row.total_net_profit
            ),
            "total_trade_count": int(
                row.total_trade_count or 0
            ),
        }

    @staticmethod
    def _text(value) -> str:
        if value is None:
            return "0"
        return str(Decimal(value))
