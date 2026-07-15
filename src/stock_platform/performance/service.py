from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.performance.models import (
    PerformanceRunType,
    StrategyPerformanceMetrics,
)
from stock_platform.performance.repository import (
    StrategyPerformanceRepository,
)


class StrategyPerformanceService:
    def __init__(self, session: Session) -> None:
        self._repository = StrategyPerformanceRepository(
            session
        )

    def create_run(
        self,
        *,
        strategy_code: str,
        run_type: PerformanceRunType,
        market_code: str,
        symbol: str | None,
        period_start_date: date,
        period_end_date: date,
        parameter_payload: dict[str, Any],
    ):
        if not strategy_code.strip():
            raise ValueError(
                "strategy_code must not be empty"
            )

        return self._repository.start_run(
            strategy_code=strategy_code.strip(),
            run_type=run_type,
            market_code=market_code.strip().upper(),
            symbol=(
                symbol.strip().upper()
                if symbol
                else None
            ),
            period_start_date=period_start_date,
            period_end_date=period_end_date,
            parameter_payload=parameter_payload,
        )

    def complete_run(
        self,
        *,
        run_id: int,
        metrics: StrategyPerformanceMetrics,
        result_payload: dict[str, Any],
    ):
        self._validate_metrics(metrics)

        return self._repository.complete_run(
            run_id=run_id,
            metrics=metrics,
            result_payload=result_payload,
        )

    @staticmethod
    def _validate_metrics(
        metrics: StrategyPerformanceMetrics,
    ) -> None:
        if metrics.initial_capital <= Decimal("0"):
            raise ValueError(
                "initial_capital must be greater than zero"
            )

        if metrics.final_capital < Decimal("0"):
            raise ValueError(
                "final_capital must not be negative"
            )

        if metrics.total_trade_count < 0:
            raise ValueError(
                "total_trade_count must not be negative"
            )

        if (
            metrics.winning_trade_count
            + metrics.losing_trade_count
            > metrics.total_trade_count
        ):
            raise ValueError(
                "winning and losing trade count exceed total"
            )
