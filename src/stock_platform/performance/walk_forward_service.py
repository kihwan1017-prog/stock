from __future__ import annotations

from sqlalchemy.orm import Session

from stock_platform.performance.models import (
    PerformanceRunType,
)
from stock_platform.performance.service import (
    StrategyPerformanceService,
)
from stock_platform.performance.walk_forward_mapper import (
    WalkForwardPerformanceMapper,
)
from stock_platform.performance.walk_forward_models import (
    WalkForwardPerformanceInput,
)
from stock_platform.performance.walk_forward_repository import (
    WalkForwardWindowMetricRepository,
)
from stock_platform.performance.walk_forward_stability import (
    WalkForwardStabilityAnalyzer,
)


class WalkForwardPerformanceIntegrationService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._performance = StrategyPerformanceService(
            session
        )
        self._windows = (
            WalkForwardWindowMetricRepository(session)
        )

    def save(
        self,
        source: WalkForwardPerformanceInput,
    ) -> dict:
        if not source.windows:
            raise ValueError(
                "Walk Forward windows must not be empty"
            )

        run = self._performance.create_run(
            strategy_code=source.strategy_code,
            run_type=PerformanceRunType.WALK_FORWARD,
            market_code=source.market_code,
            symbol=source.symbol,
            period_start_date=source.period_start_date,
            period_end_date=source.period_end_date,
            parameter_payload=(
                source.aggregate_parameter_payload
            ),
        )

        try:
            window_entities = (
                WalkForwardPerformanceMapper
                .to_window_entities(source)
            )
            aggregate_metrics = (
                WalkForwardPerformanceMapper
                .aggregate_metrics(window_entities)
            )
            stability = (
                WalkForwardStabilityAnalyzer.analyze(
                    window_entities
                )
            )

            completed = self._performance.complete_run(
                run_id=(
                    run.strategy_performance_run_id
                ),
                metrics=aggregate_metrics,
                result_payload={
                    "stability": stability,
                    "window_count": len(window_entities),
                },
            )

            self._windows.save_many(
                strategy_performance_run_id=(
                    completed
                    .strategy_performance_run_id
                ),
                rows=window_entities,
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
                "window_count": len(window_entities),
                "stability": stability,
            }

        except Exception as exc:
            self._session.rollback()
            self._performance._repository.fail_run(
                run_id=(
                    run.strategy_performance_run_id
                ),
                error_message=str(exc),
            )
            raise
