from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from itertools import product

from sqlalchemy.orm import Session

from stock_platform.backtest.grid_models import (
    BacktestGridItem,
    BacktestGridRequest,
    BacktestGridResult,
)
from stock_platform.backtest.persistence_service import (
    BacktestPersistenceService,
)


class BacktestGridService:
    """이동평균 전략 파라미터 조합을 일괄 실행하고 상위 결과를 선정한다."""

    def __init__(self, session: Session) -> None:
        self._persistence = BacktestPersistenceService(session)

    def run(
        self,
        request: BacktestGridRequest,
    ) -> BacktestGridResult:
        self._validate(request)

        combinations = list(
            product(
                request.short_windows,
                request.long_windows,
                request.stop_loss_ratios,
                request.take_profit_ratios,
                request.position_ratios,
            )
        )

        successes: list[dict] = []
        failures: list[dict] = []

        for (
            short_window,
            long_window,
            stop_loss_ratio,
            take_profit_ratio,
            position_ratio,
        ) in combinations:
            if short_window >= long_window:
                failures.append(
                    {
                        "short_window": short_window,
                        "long_window": long_window,
                        "stop_loss_ratio": str(
                            stop_loss_ratio
                        ),
                        "take_profit_ratio": str(
                            take_profit_ratio
                        ),
                        "position_ratio": str(
                            position_ratio
                        ),
                        "error": (
                            "short_window must be smaller "
                            "than long_window"
                        ),
                    }
                )
                continue

            try:
                run, result = (
                    self._persistence
                    .run_and_save_moving_average(
                        exchange_code=(
                            request.exchange_code
                        ),
                        symbol=request.symbol,
                        start_date=request.start_date,
                        end_date=request.end_date,
                        initial_capital=(
                            request.initial_capital
                        ),
                        short_window=short_window,
                        long_window=long_window,
                        stop_loss_ratio=(
                            stop_loss_ratio
                        ),
                        take_profit_ratio=(
                            take_profit_ratio
                        ),
                        position_ratio=position_ratio,
                        fee_ratio=request.fee_ratio,
                        sell_tax_ratio=(
                            request.sell_tax_ratio
                        ),
                        slippage_ratio=(
                            request.slippage_ratio
                        ),
                    )
                )

                score = self._score(
                    total_return_rate=(
                        result.summary.total_return_rate
                    ),
                    maximum_drawdown_rate=(
                        result.summary
                        .maximum_drawdown_rate
                    ),
                    win_rate=result.summary.win_rate,
                )

                successes.append(
                    {
                        "run": run,
                        "summary": result.summary,
                        "score": score,
                        "short_window": short_window,
                        "long_window": long_window,
                        "stop_loss_ratio": (
                            stop_loss_ratio
                        ),
                        "take_profit_ratio": (
                            take_profit_ratio
                        ),
                        "position_ratio": position_ratio,
                    }
                )
            except Exception as exc:
                failures.append(
                    {
                        "short_window": short_window,
                        "long_window": long_window,
                        "stop_loss_ratio": str(
                            stop_loss_ratio
                        ),
                        "take_profit_ratio": str(
                            take_profit_ratio
                        ),
                        "position_ratio": str(
                            position_ratio
                        ),
                        "error": str(exc),
                    }
                )

        successes.sort(
            key=lambda item: (
                item["score"],
                item["summary"].total_return_rate,
                -item["summary"]
                .maximum_drawdown_rate,
            ),
            reverse=True,
        )

        top_results = [
            BacktestGridItem(
                rank_no=rank_no,
                backtest_run_id=(
                    item["run"].backtest_run_id
                ),
                short_window=item["short_window"],
                long_window=item["long_window"],
                stop_loss_ratio=(
                    item["stop_loss_ratio"]
                ),
                take_profit_ratio=(
                    item["take_profit_ratio"]
                ),
                position_ratio=item["position_ratio"],
                total_return_rate=(
                    item["summary"].total_return_rate
                ),
                maximum_drawdown_rate=(
                    item["summary"]
                    .maximum_drawdown_rate
                ),
                win_rate=item["summary"].win_rate,
                trade_count=item["summary"].trade_count,
                final_equity=(
                    item["summary"].final_equity
                ),
                score=item["score"],
            )
            for rank_no, item in enumerate(
                successes[:request.top_n],
                start=1,
            )
        ]

        return BacktestGridResult(
            exchange_code=request.exchange_code.upper(),
            symbol=request.symbol.upper(),
            combination_count=len(combinations),
            success_count=len(successes),
            failed_count=len(failures),
            top_results=top_results,
            failures=failures,
        )

    @staticmethod
    def _score(
        *,
        total_return_rate: Decimal,
        maximum_drawdown_rate: Decimal,
        win_rate: Decimal,
    ) -> Decimal:
        return (
            total_return_rate
            - maximum_drawdown_rate
            + win_rate * Decimal("0.10")
        ).quantize(Decimal("0.0001"))

    @staticmethod
    def _validate(
        request: BacktestGridRequest,
    ) -> None:
        if request.start_date > request.end_date:
            raise ValueError(
                "start_date must not be after end_date"
            )

        if request.initial_capital <= 0:
            raise ValueError(
                "initial_capital must be greater than zero"
            )

        if not request.short_windows:
            raise ValueError(
                "short_windows must not be empty"
            )

        if not request.long_windows:
            raise ValueError(
                "long_windows must not be empty"
            )

        if not request.stop_loss_ratios:
            raise ValueError(
                "stop_loss_ratios must not be empty"
            )

        if not request.take_profit_ratios:
            raise ValueError(
                "take_profit_ratios must not be empty"
            )

        if not request.position_ratios:
            raise ValueError(
                "position_ratios must not be empty"
            )

        if request.top_n <= 0:
            raise ValueError(
                "top_n must be greater than zero"
            )

        combination_count = (
            len(request.short_windows)
            * len(request.long_windows)
            * len(request.stop_loss_ratios)
            * len(request.take_profit_ratios)
            * len(request.position_ratios)
        )

        if combination_count > 500:
            raise ValueError(
                "parameter combination count must not "
                "exceed 500"
            )
