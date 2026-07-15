from __future__ import annotations

import os

from stock_platform.database.session import (
    get_session_factory,
)
from stock_platform.strategy_deployment.performance_monitor_models import (
    DeploymentPerformancePolicy,
)
from stock_platform.strategy_deployment.performance_monitor_service import (
    DeploymentPerformanceMonitorService,
)
from stock_platform.strategy_deployment.repository import (
    StrategyDeploymentRepository,
)


class DeploymentPerformanceMonitorManager:
    def __init__(self) -> None:
        self._last_result = None
        self._last_error: str | None = None

    def check_active(
        self,
        *,
        market_code: str,
        symbol: str | None,
    ):
        session = get_session_factory()()

        try:
            deployment = StrategyDeploymentRepository(
                session
            ).get_active(
                market_code=market_code,
                symbol=symbol,
                mode_code="PAPER",
            )

            if deployment is None:
                raise LookupError(
                    "Active PAPER strategy deployment "
                    "not found"
                )

            policy = DeploymentPerformancePolicy(
                auto_stop_enabled=(
                    os.getenv(
                        "PAPER_STRATEGY_AUTO_STOP_ENABLED",
                        "false",
                    ).lower()
                    == "true"
                )
            )

            result = (
                DeploymentPerformanceMonitorService(
                    session=session,
                    policy=policy,
                ).check(
                    deployment_id=(
                        deployment
                        .strategy_deployment_id
                    )
                )
            )
            self._last_result = result
            self._last_error = None
            return result

        except Exception as exc:
            session.rollback()
            self._last_error = str(exc)
            raise
        finally:
            session.close()

    def status(self):
        return {
            "last_result": self._last_result,
            "last_error": self._last_error,
        }


deployment_performance_monitor_manager = (
    DeploymentPerformanceMonitorManager()
)
