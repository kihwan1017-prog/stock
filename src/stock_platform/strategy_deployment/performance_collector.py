from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.performance.entities import (
    StrategyPerformanceMetricEntity,
    StrategyPerformanceRunEntity,
)
from stock_platform.strategy_deployment.entities import (
    StrategyDeploymentEntity,
)


ZERO = Decimal("0")


class PaperDeploymentPerformanceCollector:
    """
    PAPER 배치와 연결된 최신 PAPER 성과 Run을 조회한다.

    실제 체결/포지션 기반 집계가 이미 존재하면 이 클래스의 쿼리를
    프로젝트 구조에 맞게 교체한다.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def collect(
        self,
        *,
        deployment_id: int,
    ) -> dict:
        deployment = self._session.get(
            StrategyDeploymentEntity,
            deployment_id,
        )

        if deployment is None:
            raise LookupError(
                "Strategy deployment not found"
            )

        run = self._session.scalar(
            select(StrategyPerformanceRunEntity)
            .where(
                StrategyPerformanceRunEntity.strategy_code
                == deployment.strategy_code,
                StrategyPerformanceRunEntity.market_code
                == deployment.market_code,
                StrategyPerformanceRunEntity.symbol
                == deployment.symbol,
                StrategyPerformanceRunEntity.run_type
                == "PAPER",
                StrategyPerformanceRunEntity.status_code
                == "COMPLETED",
            )
            .order_by(
                StrategyPerformanceRunEntity
                .completed_at.desc(),
                StrategyPerformanceRunEntity
                .strategy_performance_run_id.desc(),
            )
            .limit(1)
        )

        if run is None:
            return {
                "deployment": deployment,
                "metric": None,
                "performance_run": None,
                "consecutive_losses": 0,
            }

        metric = self._session.scalar(
            select(StrategyPerformanceMetricEntity)
            .where(
                StrategyPerformanceMetricEntity
                .strategy_performance_run_id
                == run.strategy_performance_run_id
            )
            .limit(1)
        )

        consecutive_losses = int(
            (run.result_payload or {}).get(
                "maximum_consecutive_losses",
                (run.result_payload or {}).get(
                    "consecutive_losses",
                    0,
                ),
            )
        )

        return {
            "deployment": deployment,
            "metric": metric,
            "performance_run": run,
            "consecutive_losses": consecutive_losses,
        }
