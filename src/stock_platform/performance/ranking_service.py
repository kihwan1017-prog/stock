from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.performance.entities import (
    StrategyPerformanceMetricEntity,
    StrategyPerformanceRunEntity,
)
from stock_platform.performance.ranking_models import (
    StrategyRankingItem,
    StrategyRankingWeights,
)


ZERO = Decimal("0")
ONE = Decimal("1")


class StrategyPerformanceRankingService:
    """
    완료된 전략 성과를 동일 그룹 내에서 0~1 정규화한 뒤
    가중합 점수로 순위를 계산한다.
    """

    def __init__(
        self,
        session: Session,
        *,
        weights: StrategyRankingWeights | None = None,
    ) -> None:
        self._session = session
        self._weights = (
            weights or StrategyRankingWeights()
        )
        self._weights.validate()

    def rank(
        self,
        *,
        run_type: str | None = None,
        market_code: str | None = None,
        symbol: str | None = None,
        minimum_trade_count: int = 1,
        limit: int = 50,
    ) -> list[StrategyRankingItem]:
        if minimum_trade_count < 0:
            raise ValueError(
                "minimum_trade_count must not be negative"
            )

        if limit < 1 or limit > 500:
            raise ValueError(
                "limit must be between 1 and 500"
            )

        statement = (
            select(
                StrategyPerformanceRunEntity,
                StrategyPerformanceMetricEntity,
            )
            .join(
                StrategyPerformanceMetricEntity,
                StrategyPerformanceMetricEntity
                .strategy_performance_run_id
                == StrategyPerformanceRunEntity
                .strategy_performance_run_id,
            )
            .where(
                StrategyPerformanceRunEntity.status_code
                == "COMPLETED",
                StrategyPerformanceMetricEntity
                .total_trade_count
                >= minimum_trade_count,
            )
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

        if symbol:
            statement = statement.where(
                StrategyPerformanceRunEntity.symbol
                == symbol.upper()
            )

        rows = list(
            self._session.execute(statement).all()
        )

        if not rows:
            return []

        metrics = [
            {
                "run": run,
                "metric": metric,
                "return_rate": Decimal(
                    metric.total_return_rate
                ),
                "mdd": Decimal(
                    metric.maximum_drawdown_rate
                ),
                "sharpe": self._optional_decimal(
                    metric.sharpe_ratio
                ),
                "sortino": self._optional_decimal(
                    metric.sortino_ratio
                ),
                "win_rate": Decimal(metric.win_rate),
                "profit_factor": self._optional_decimal(
                    metric.profit_factor
                ),
            }
            for run, metric in rows
        ]

        normalized = self._normalize(metrics)

        ranked = sorted(
            normalized,
            key=lambda item: (
                item["score"],
                item["return_rate"],
                -item["mdd"],
            ),
            reverse=True,
        )[:limit]

        return [
            StrategyRankingItem(
                rank=index,
                strategy_code=item["run"].strategy_code,
                market_code=item["run"].market_code,
                symbol=item["run"].symbol,
                run_type=item["run"].run_type,
                score=item["score"],
                total_return_rate=item["return_rate"],
                maximum_drawdown_rate=item["mdd"],
                sharpe_ratio=item["sharpe"],
                sortino_ratio=item["sortino"],
                win_rate=item["win_rate"],
                profit_factor=item["profit_factor"],
                total_trade_count=(
                    item["metric"].total_trade_count
                ),
                strategy_performance_run_id=(
                    item["run"]
                    .strategy_performance_run_id
                ),
            )
            for index, item in enumerate(
                ranked,
                start=1,
            )
        ]

    def _normalize(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ranges = {
            "return_rate": self._range(
                [item["return_rate"] for item in rows]
            ),
            "sharpe": self._range(
                [
                    item["sharpe"] or ZERO
                    for item in rows
                ]
            ),
            "sortino": self._range(
                [
                    item["sortino"] or ZERO
                    for item in rows
                ]
            ),
            "win_rate": self._range(
                [item["win_rate"] for item in rows]
            ),
            "profit_factor": self._range(
                [
                    item["profit_factor"] or ZERO
                    for item in rows
                ]
            ),
            "mdd": self._range(
                [item["mdd"] for item in rows]
            ),
        }

        result = []

        for item in rows:
            return_score = self._scale(
                item["return_rate"],
                ranges["return_rate"],
            )
            sharpe_score = self._scale(
                item["sharpe"] or ZERO,
                ranges["sharpe"],
            )
            sortino_score = self._scale(
                item["sortino"] or ZERO,
                ranges["sortino"],
            )
            win_rate_score = self._scale(
                item["win_rate"],
                ranges["win_rate"],
            )
            profit_factor_score = self._scale(
                item["profit_factor"] or ZERO,
                ranges["profit_factor"],
            )
            mdd_score = ONE - self._scale(
                item["mdd"],
                ranges["mdd"],
            )

            score = (
                return_score
                * self._weights.return_rate
                + sharpe_score
                * self._weights.sharpe_ratio
                + sortino_score
                * self._weights.sortino_ratio
                + win_rate_score
                * self._weights.win_rate
                + profit_factor_score
                * self._weights.profit_factor
                + mdd_score
                * self._weights.maximum_drawdown
            ).quantize(Decimal("0.00000001"))

            result.append(
                {
                    **item,
                    "score": score,
                }
            )

        return result

    @staticmethod
    def _range(
        values: list[Decimal],
    ) -> tuple[Decimal, Decimal]:
        return min(values), max(values)

    @staticmethod
    def _scale(
        value: Decimal,
        value_range: tuple[Decimal, Decimal],
    ) -> Decimal:
        minimum, maximum = value_range

        if minimum == maximum:
            return ONE

        return (
            value - minimum
        ) / (
            maximum - minimum
        )

    @staticmethod
    def _optional_decimal(
        value,
    ) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value)
