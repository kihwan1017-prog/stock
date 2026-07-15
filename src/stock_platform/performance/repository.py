from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.performance.entities import (
    StrategyPerformanceMetricEntity,
    StrategyPerformanceRunEntity,
)
from stock_platform.performance.models import (
    PerformanceRunStatus,
    PerformanceRunType,
    StrategyPerformanceMetrics,
)


class StrategyPerformanceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def start_run(
        self,
        *,
        strategy_code: str,
        run_type: PerformanceRunType,
        market_code: str,
        symbol: str | None,
        period_start_date: date,
        period_end_date: date,
        parameter_payload: dict[str, Any],
    ) -> StrategyPerformanceRunEntity:
        if period_start_date > period_end_date:
            raise ValueError(
                "period_start_date must not be after period_end_date"
            )

        parameter_hash = self._parameter_hash(
            parameter_payload
        )

        entity = StrategyPerformanceRunEntity(
            strategy_code=strategy_code,
            run_type=run_type.value,
            status_code=PerformanceRunStatus.RUNNING.value,
            market_code=market_code,
            symbol=symbol,
            period_start_date=period_start_date,
            period_end_date=period_end_date,
            parameter_hash=parameter_hash,
            parameter_payload=parameter_payload,
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def complete_run(
        self,
        *,
        run_id: int,
        metrics: StrategyPerformanceMetrics,
        result_payload: dict[str, Any],
    ) -> StrategyPerformanceRunEntity:
        entity = self._session.get(
            StrategyPerformanceRunEntity,
            run_id,
        )

        if entity is None:
            raise LookupError(
                "Strategy performance run not found"
            )

        entity.status_code = (
            PerformanceRunStatus.COMPLETED.value
        )
        entity.result_payload = result_payload
        entity.completed_at = datetime.now(timezone.utc)

        metric = StrategyPerformanceMetricEntity(
            strategy_performance_run_id=run_id,
            initial_capital=metrics.initial_capital,
            final_capital=metrics.final_capital,
            total_return_rate=metrics.total_return_rate,
            annualized_return_rate=(
                metrics.annualized_return_rate
            ),
            maximum_drawdown_rate=(
                metrics.maximum_drawdown_rate
            ),
            volatility_rate=metrics.volatility_rate,
            sharpe_ratio=metrics.sharpe_ratio,
            sortino_ratio=metrics.sortino_ratio,
            win_rate=metrics.win_rate,
            profit_factor=metrics.profit_factor,
            total_trade_count=metrics.total_trade_count,
            winning_trade_count=(
                metrics.winning_trade_count
            ),
            losing_trade_count=(
                metrics.losing_trade_count
            ),
            average_profit_amount=(
                metrics.average_profit_amount
            ),
            average_loss_amount=(
                metrics.average_loss_amount
            ),
            gross_profit_amount=(
                metrics.gross_profit_amount
            ),
            gross_loss_amount=metrics.gross_loss_amount,
            net_profit_amount=metrics.net_profit_amount,
        )
        self._session.add(metric)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def fail_run(
        self,
        *,
        run_id: int,
        error_message: str,
    ) -> StrategyPerformanceRunEntity:
        entity = self._session.get(
            StrategyPerformanceRunEntity,
            run_id,
        )

        if entity is None:
            raise LookupError(
                "Strategy performance run not found"
            )

        entity.status_code = (
            PerformanceRunStatus.FAILED.value
        )
        entity.error_message = error_message
        entity.completed_at = datetime.now(timezone.utc)

        self._session.commit()
        self._session.refresh(entity)
        return entity

    def get_detail(
        self,
        *,
        run_id: int,
    ) -> tuple[
        StrategyPerformanceRunEntity | None,
        StrategyPerformanceMetricEntity | None,
    ]:
        run = self._session.get(
            StrategyPerformanceRunEntity,
            run_id,
        )

        metric = self._session.scalar(
            select(StrategyPerformanceMetricEntity).where(
                StrategyPerformanceMetricEntity
                .strategy_performance_run_id
                == run_id
            )
        )

        return run, metric

    @staticmethod
    def _parameter_hash(
        payload: dict[str, Any],
    ) -> str:
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()
