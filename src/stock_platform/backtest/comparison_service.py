from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.backtest.persistence_models import (
    BacktestRunEntity,
)
from stock_platform.backtest.repository import BacktestRepository


@dataclass(frozen=True, slots=True)
class BacktestComparisonItem:
    rank_no: int
    backtest_run_id: int
    strategy_code: str
    exchange_code: str
    symbol: str
    total_return_rate: Decimal
    maximum_drawdown_rate: Decimal
    win_rate: Decimal
    trade_count: int
    final_equity: Decimal
    score: Decimal
    parameters: dict


class BacktestComparisonService:
    """
    저장된 백테스트 결과를 수익률, 최대낙폭, 승률 기준으로
    단순 비교한다.
    """

    def __init__(self, session: Session) -> None:
        self._repository = BacktestRepository(session)

    def compare(
        self,
        *,
        exchange_code: str | None = None,
        symbol: str | None = None,
        strategy_code: str | None = None,
        limit: int = 20,
    ) -> list[BacktestComparisonItem]:
        runs = self._repository.list_runs(
            exchange_code=exchange_code,
            symbol=symbol,
            strategy_code=strategy_code,
            limit=limit,
        )

        scored = [
            (
                run,
                self._score(run),
            )
            for run in runs
        ]

        scored.sort(
            key=lambda item: (
                item[1],
                item[0].total_return_rate,
                -item[0].maximum_drawdown_rate,
            ),
            reverse=True,
        )

        return [
            BacktestComparisonItem(
                rank_no=index,
                backtest_run_id=run.backtest_run_id,
                strategy_code=run.strategy_code,
                exchange_code=run.exchange_code,
                symbol=run.symbol,
                total_return_rate=run.total_return_rate,
                maximum_drawdown_rate=(
                    run.maximum_drawdown_rate
                ),
                win_rate=run.win_rate,
                trade_count=run.trade_count,
                final_equity=run.final_equity,
                score=score,
                parameters=run.parameters,
            )
            for index, (run, score) in enumerate(
                scored,
                start=1,
            )
        ]

    @staticmethod
    def _score(
        run: BacktestRunEntity,
    ) -> Decimal:
        return (
            Decimal(run.total_return_rate)
            - Decimal(run.maximum_drawdown_rate)
            + Decimal(run.win_rate)
            * Decimal("0.10")
        ).quantize(Decimal("0.0001"))
