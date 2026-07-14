from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from itertools import product

from sqlalchemy.orm import Session

from stock_platform.backtest.persistence_service import (
    BacktestPersistenceService,
)
from stock_platform.backtest.walk_forward_models import (
    WalkForwardParameterSet,
    WalkForwardResult,
    WalkForwardSummary,
    WalkForwardWindow,
    WalkForwardWindowResult,
)


ZERO = Decimal("0")
ONE = Decimal("1")


class WalkForwardValidationService:
    """
    학습 구간에서 최적 파라미터를 선택하고 바로 다음 검증 구간에서
    동일 파라미터를 평가한다.
    """

    def __init__(self, session: Session) -> None:
        self._persistence = BacktestPersistenceService(session)

    def run(
        self,
        *,
        exchange_code: str,
        symbol: str,
        start_date: date,
        end_date: date,
        initial_capital: Decimal,
        train_months: int,
        test_months: int,
        short_windows: list[int],
        long_windows: list[int],
        stop_loss_ratios: list[Decimal],
        take_profit_ratios: list[Decimal],
        position_ratios: list[Decimal],
        fee_ratio: Decimal,
        sell_tax_ratio: Decimal,
        slippage_ratio: Decimal,
    ) -> WalkForwardResult:
        self._validate(
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            train_months=train_months,
            test_months=test_months,
            short_windows=short_windows,
            long_windows=long_windows,
            stop_loss_ratios=stop_loss_ratios,
            take_profit_ratios=take_profit_ratios,
            position_ratios=position_ratios,
        )

        windows = self._build_windows(
            start_date=start_date,
            end_date=end_date,
            train_months=train_months,
            test_months=test_months,
        )

        combinations = [
            WalkForwardParameterSet(
                short_window=short_window,
                long_window=long_window,
                stop_loss_ratio=stop_loss_ratio,
                take_profit_ratio=take_profit_ratio,
                position_ratio=position_ratio,
            )
            for (
                short_window,
                long_window,
                stop_loss_ratio,
                take_profit_ratio,
                position_ratio,
            ) in product(
                short_windows,
                long_windows,
                stop_loss_ratios,
                take_profit_ratios,
                position_ratios,
            )
            if short_window < long_window
        ]

        results: list[WalkForwardWindowResult] = []
        failures: list[dict] = []

        for window in windows:
            try:
                selected = self._select_best_parameters(
                    exchange_code=exchange_code,
                    symbol=symbol,
                    window=window,
                    initial_capital=initial_capital,
                    combinations=combinations,
                    fee_ratio=fee_ratio,
                    sell_tax_ratio=sell_tax_ratio,
                    slippage_ratio=slippage_ratio,
                )

                (
                    selected_parameters,
                    train_run,
                    train_result,
                    train_score,
                ) = selected

                test_run, test_result = (
                    self._persistence
                    .run_and_save_moving_average(
                        exchange_code=exchange_code,
                        symbol=symbol,
                        start_date=window.test_start_date,
                        end_date=window.test_end_date,
                        initial_capital=initial_capital,
                        short_window=(
                            selected_parameters.short_window
                        ),
                        long_window=(
                            selected_parameters.long_window
                        ),
                        stop_loss_ratio=(
                            selected_parameters
                            .stop_loss_ratio
                        ),
                        take_profit_ratio=(
                            selected_parameters
                            .take_profit_ratio
                        ),
                        position_ratio=(
                            selected_parameters.position_ratio
                        ),
                        fee_ratio=fee_ratio,
                        sell_tax_ratio=sell_tax_ratio,
                        slippage_ratio=slippage_ratio,
                    )
                )

                results.append(
                    WalkForwardWindowResult(
                        window_no=window.window_no,
                        train_start_date=(
                            window.train_start_date
                        ),
                        train_end_date=window.train_end_date,
                        test_start_date=(
                            window.test_start_date
                        ),
                        test_end_date=window.test_end_date,
                        selected_parameters=(
                            selected_parameters
                        ),
                        train_backtest_run_id=(
                            train_run.backtest_run_id
                        ),
                        test_backtest_run_id=(
                            test_run.backtest_run_id
                        ),
                        train_score=train_score,
                        train_return_rate=(
                            train_result.summary
                            .total_return_rate
                        ),
                        train_maximum_drawdown_rate=(
                            train_result.summary
                            .maximum_drawdown_rate
                        ),
                        test_return_rate=(
                            test_result.summary
                            .total_return_rate
                        ),
                        test_maximum_drawdown_rate=(
                            test_result.summary
                            .maximum_drawdown_rate
                        ),
                        test_win_rate=(
                            test_result.summary.win_rate
                        ),
                        test_trade_count=(
                            test_result.summary.trade_count
                        ),
                    )
                )
            except Exception as exc:
                failures.append(
                    {
                        "window_no": window.window_no,
                        "train_start_date": (
                            window.train_start_date.isoformat()
                        ),
                        "train_end_date": (
                            window.train_end_date.isoformat()
                        ),
                        "test_start_date": (
                            window.test_start_date.isoformat()
                        ),
                        "test_end_date": (
                            window.test_end_date.isoformat()
                        ),
                        "error": str(exc),
                    }
                )

        summary = self._build_summary(
            total_window_count=len(windows),
            results=results,
            failures=failures,
        )

        return WalkForwardResult(
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
            start_date=start_date,
            end_date=end_date,
            train_months=train_months,
            test_months=test_months,
            summary=summary,
            windows=results,
            failures=failures,
        )

    def _select_best_parameters(
        self,
        *,
        exchange_code: str,
        symbol: str,
        window: WalkForwardWindow,
        initial_capital: Decimal,
        combinations: list[WalkForwardParameterSet],
        fee_ratio: Decimal,
        sell_tax_ratio: Decimal,
        slippage_ratio: Decimal,
    ):
        candidates: list[tuple] = []

        for parameters in combinations:
            try:
                run, result = (
                    self._persistence
                    .run_and_save_moving_average(
                        exchange_code=exchange_code,
                        symbol=symbol,
                        start_date=window.train_start_date,
                        end_date=window.train_end_date,
                        initial_capital=initial_capital,
                        short_window=(
                            parameters.short_window
                        ),
                        long_window=parameters.long_window,
                        stop_loss_ratio=(
                            parameters.stop_loss_ratio
                        ),
                        take_profit_ratio=(
                            parameters.take_profit_ratio
                        ),
                        position_ratio=(
                            parameters.position_ratio
                        ),
                        fee_ratio=fee_ratio,
                        sell_tax_ratio=sell_tax_ratio,
                        slippage_ratio=slippage_ratio,
                    )
                )
            except Exception:
                continue

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

            candidates.append(
                (
                    parameters,
                    run,
                    result,
                    score,
                )
            )

        if not candidates:
            raise RuntimeError(
                "No successful training backtest"
            )

        candidates.sort(
            key=lambda item: (
                item[3],
                item[2].summary.total_return_rate,
                -item[2].summary
                .maximum_drawdown_rate,
            ),
            reverse=True,
        )

        return candidates[0]

    @staticmethod
    def _build_windows(
        *,
        start_date: date,
        end_date: date,
        train_months: int,
        test_months: int,
    ) -> list[WalkForwardWindow]:
        windows: list[WalkForwardWindow] = []
        window_no = 1
        train_start = start_date

        while True:
            train_end = (
                WalkForwardValidationService._add_months(
                    train_start,
                    train_months,
                )
                - timedelta(days=1)
            )
            test_start = train_end + timedelta(days=1)
            test_end = (
                WalkForwardValidationService._add_months(
                    test_start,
                    test_months,
                )
                - timedelta(days=1)
            )

            if test_start > end_date:
                break

            test_end = min(test_end, end_date)

            windows.append(
                WalkForwardWindow(
                    window_no=window_no,
                    train_start_date=train_start,
                    train_end_date=train_end,
                    test_start_date=test_start,
                    test_end_date=test_end,
                )
            )

            if test_end >= end_date:
                break

            train_start = (
                WalkForwardValidationService._add_months(
                    train_start,
                    test_months,
                )
            )
            window_no += 1

        return windows

    @staticmethod
    def _build_summary(
        *,
        total_window_count: int,
        results: list[WalkForwardWindowResult],
        failures: list[dict],
    ) -> WalkForwardSummary:
        completed_count = len(results)

        if completed_count == 0:
            return WalkForwardSummary(
                window_count=total_window_count,
                completed_window_count=0,
                failed_window_count=len(failures),
                average_test_return_rate=ZERO,
                compounded_test_return_rate=ZERO,
                average_test_maximum_drawdown_rate=ZERO,
                profitable_window_count=0,
                profitable_window_rate=ZERO,
                parameter_change_count=0,
            )

        average_return = (
            sum(
                (
                    item.test_return_rate
                    for item in results
                ),
                ZERO,
            )
            / Decimal(completed_count)
        ).quantize(Decimal("0.0001"))

        average_drawdown = (
            sum(
                (
                    item.test_maximum_drawdown_rate
                    for item in results
                ),
                ZERO,
            )
            / Decimal(completed_count)
        ).quantize(Decimal("0.0001"))

        compounded_factor = ONE
        profitable_count = 0
        parameter_change_count = 0
        previous_parameters = None

        for item in results:
            compounded_factor *= (
                ONE
                + item.test_return_rate
                / Decimal("100")
            )

            if item.test_return_rate > ZERO:
                profitable_count += 1

            if (
                previous_parameters is not None
                and previous_parameters
                != item.selected_parameters
            ):
                parameter_change_count += 1

            previous_parameters = item.selected_parameters

        compounded_return = (
            (compounded_factor - ONE)
            * Decimal("100")
        ).quantize(Decimal("0.0001"))

        profitable_rate = (
            Decimal(profitable_count)
            / Decimal(completed_count)
            * Decimal("100")
        ).quantize(Decimal("0.0001"))

        return WalkForwardSummary(
            window_count=total_window_count,
            completed_window_count=completed_count,
            failed_window_count=len(failures),
            average_test_return_rate=average_return,
            compounded_test_return_rate=(
                compounded_return
            ),
            average_test_maximum_drawdown_rate=(
                average_drawdown
            ),
            profitable_window_count=profitable_count,
            profitable_window_rate=profitable_rate,
            parameter_change_count=(
                parameter_change_count
            ),
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
    def _add_months(
        value: date,
        months: int,
    ) -> date:
        month_index = value.month - 1 + months
        year = value.year + month_index // 12
        month = month_index % 12 + 1
        day = min(
            value.day,
            monthrange(year, month)[1],
        )
        return date(year, month, day)

    @staticmethod
    def _validate(
        *,
        start_date: date,
        end_date: date,
        initial_capital: Decimal,
        train_months: int,
        test_months: int,
        short_windows: list[int],
        long_windows: list[int],
        stop_loss_ratios: list[Decimal],
        take_profit_ratios: list[Decimal],
        position_ratios: list[Decimal],
    ) -> None:
        if start_date >= end_date:
            raise ValueError(
                "start_date must be before end_date"
            )

        if initial_capital <= ZERO:
            raise ValueError(
                "initial_capital must be greater than zero"
            )

        if train_months <= 0:
            raise ValueError(
                "train_months must be greater than zero"
            )

        if test_months <= 0:
            raise ValueError(
                "test_months must be greater than zero"
            )

        if not short_windows or not long_windows:
            raise ValueError(
                "moving average windows must not be empty"
            )

        if (
            not stop_loss_ratios
            or not take_profit_ratios
            or not position_ratios
        ):
            raise ValueError(
                "ratio parameter lists must not be empty"
            )

        combination_count = (
            len(short_windows)
            * len(long_windows)
            * len(stop_loss_ratios)
            * len(take_profit_ratios)
            * len(position_ratios)
        )

        if combination_count > 200:
            raise ValueError(
                "walk-forward parameter combination count "
                "must not exceed 200"
            )
