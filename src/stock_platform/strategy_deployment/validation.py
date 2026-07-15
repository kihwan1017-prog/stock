from __future__ import annotations

from sqlalchemy.orm import Session

from stock_platform.performance.entities import (
    StrategyPerformanceRunEntity,
)


class StrategyDeploymentValidator:
    def __init__(self, session: Session) -> None:
        self._session = session

    def validate_performance_run(
        self,
        *,
        performance_run_id: int,
        strategy_code: str,
        market_code: str,
        symbol: str | None,
    ) -> StrategyPerformanceRunEntity:
        run = self._session.get(
            StrategyPerformanceRunEntity,
            performance_run_id,
        )

        if run is None:
            raise LookupError(
                "Strategy performance run not found"
            )

        if run.status_code != "COMPLETED":
            raise ValueError(
                "Only COMPLETED performance runs can be deployed"
            )

        if run.strategy_code != strategy_code:
            raise ValueError(
                "strategy_code does not match performance run"
            )

        if run.market_code != market_code.upper():
            raise ValueError(
                "market_code does not match performance run"
            )

        expected_symbol = (
            symbol.upper()
            if symbol
            else None
        )

        if run.symbol != expected_symbol:
            raise ValueError(
                "symbol does not match performance run"
            )

        if run.run_type not in {
            "WALK_FORWARD",
            "PAPER",
        }:
            raise ValueError(
                "Initial deployment requires WALK_FORWARD or PAPER performance"
            )

        return run
