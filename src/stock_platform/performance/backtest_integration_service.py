from __future__ import annotations

from sqlalchemy.orm import Session

from stock_platform.performance.backtest_mapper import (
    BacktestPerformanceMapper,
)
from stock_platform.performance.backtest_models import (
    BacktestPerformanceInput,
)
from stock_platform.performance.models import (
    PerformanceRunType,
)
from stock_platform.performance.service import (
    StrategyPerformanceService,
)


class BacktestPerformanceIntegrationService:
    """
    기존 백테스트 완료 결과를 전략 성과 Run/Metric으로 자동 저장한다.
    """

    def __init__(self, session: Session) -> None:
        self._service = StrategyPerformanceService(
            session
        )

    def save_completed_backtest(
        self,
        source: BacktestPerformanceInput,
    ) -> dict:
        run = self._service.create_run(
            strategy_code=source.strategy_code,
            run_type=PerformanceRunType.BACKTEST,
            market_code=source.market_code,
            symbol=source.symbol,
            period_start_date=(
                source.period_start_date
            ),
            period_end_date=source.period_end_date,
            parameter_payload=(
                source.parameter_payload
            ),
        )

        try:
            completed = self._service.complete_run(
                run_id=(
                    run.strategy_performance_run_id
                ),
                metrics=(
                    BacktestPerformanceMapper
                    .to_metrics(source)
                ),
                result_payload=(
                    source.result_payload or {}
                ),
            )

            return {
                "strategy_performance_run_id": (
                    completed
                    .strategy_performance_run_id
                ),
                "strategy_code": (
                    completed.strategy_code
                ),
                "run_type": completed.run_type,
                "status_code": completed.status_code,
                "period_start_date": (
                    completed.period_start_date
                ),
                "period_end_date": (
                    completed.period_end_date
                ),
                "completed_at": (
                    completed.completed_at
                ),
            }

        except Exception as exc:
            self._service._repository.fail_run(
                run_id=(
                    run.strategy_performance_run_id
                ),
                error_message=str(exc),
            )
            raise
