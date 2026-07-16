from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.entities import (
    StrategyDeploymentEntity,
)
from stock_platform.strategy_deployment.performance_monitor_entities import (
    StrategyDeploymentPerformanceEntity,
)
from stock_platform.strategy_deployment.pipeline_entities import (
    StrategyDeploymentPipelineEntity,
)
from stock_platform.strategy_deployment.policy_entities import (
    StrategyApprovalRunEntity,
)
from stock_platform.strategy_deployment.repository import (
    StrategyDeploymentRepository,
)
from stock_platform.strategy_deployment.runtime_manager import (
    dynamic_strategy_runtime_manager,
)
from stock_platform.strategy_deployment.switch_entities import (
    StrategyRuntimeSwitchEntity,
)


class StrategyOperationsDashboardService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def build(
        self,
        *,
        market_code: str,
        symbol: str | None,
        limit: int = 20,
    ):
        if not market_code.strip():
            raise ValueError(
                "market_code must not be empty"
            )

        if limit < 1 or limit > 200:
            raise ValueError(
                "limit must be between 1 and 200"
            )

        normalized_market = market_code.upper()
        normalized_symbol = (
            symbol.upper()
            if symbol
            else None
        )

        active = StrategyDeploymentRepository(
            self._session
        ).get_active(
            market_code=normalized_market,
            symbol=normalized_symbol,
            mode_code="PAPER",
        )

        recent_deployments = self._recent_deployments(
            market_code=normalized_market,
            symbol=normalized_symbol,
            limit=limit,
        )
        recent_approvals = self._recent_approvals(
            market_code=normalized_market,
            symbol=normalized_symbol,
            limit=limit,
        )
        recent_switches = self._recent_switches(
            limit=limit
        )
        recent_pipeline_runs = self._recent_pipelines(
            market_code=normalized_market,
            symbol=normalized_symbol,
            limit=limit,
        )
        recent_performance_checks = (
            self._recent_performance_checks(
                deployment_id=(
                    active.strategy_deployment_id
                    if active is not None
                    else None
                ),
                limit=limit,
            )
        )

        return {
            "generated_at": datetime.now(timezone.utc),
            "market_code": normalized_market,
            "symbol": normalized_symbol,
            "active_deployment": (
                self._deployment_to_dict(active)
                if active is not None
                else None
            ),
            "runtime": (
                dynamic_strategy_runtime_manager.status()
            ),
            "latest_approval": (
                recent_approvals[0]
                if recent_approvals
                else None
            ),
            "latest_pipeline": (
                recent_pipeline_runs[0]
                if recent_pipeline_runs
                else None
            ),
            "latest_performance": (
                recent_performance_checks[0]
                if recent_performance_checks
                else None
            ),
            "recent_deployments": recent_deployments,
            "recent_approvals": recent_approvals,
            "recent_switches": recent_switches,
            "recent_pipeline_runs": recent_pipeline_runs,
            "recent_performance_checks": (
                recent_performance_checks
            ),
        }

    def _recent_deployments(
        self,
        *,
        market_code: str,
        symbol: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        statement = select(
            StrategyDeploymentEntity
        ).where(
            StrategyDeploymentEntity.market_code
            == market_code
        )

        if symbol is None:
            statement = statement.where(
                StrategyDeploymentEntity.symbol.is_(None)
            )
        else:
            statement = statement.where(
                StrategyDeploymentEntity.symbol
                == symbol
            )

        rows = list(
            self._session.scalars(
                statement.order_by(
                    StrategyDeploymentEntity
                    .strategy_deployment_id.desc()
                )
                .limit(limit)
            )
        )

        return [
            self._deployment_to_dict(item)
            for item in rows
        ]

    def _recent_approvals(
        self,
        *,
        market_code: str,
        symbol: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        statement = select(
            StrategyApprovalRunEntity
        ).where(
            StrategyApprovalRunEntity.market_code
            == market_code
        )

        if symbol is None:
            statement = statement.where(
                StrategyApprovalRunEntity.symbol.is_(None)
            )
        else:
            statement = statement.where(
                StrategyApprovalRunEntity.symbol
                == symbol
            )

        rows = list(
            self._session.scalars(
                statement.order_by(
                    StrategyApprovalRunEntity
                    .strategy_approval_run_id.desc()
                )
                .limit(limit)
            )
        )

        return [
            {
                "strategy_approval_run_id": (
                    item.strategy_approval_run_id
                ),
                "strategy_selection_run_id": (
                    item.strategy_selection_run_id
                ),
                "strategy_performance_run_id": (
                    item.strategy_performance_run_id
                ),
                "strategy_code": item.strategy_code,
                "market_code": item.market_code,
                "symbol": item.symbol,
                "decision_code": item.decision_code,
                "status_code": item.status_code,
                "automatic_approval": (
                    item.automatic_approval
                ),
                "requested_by": item.requested_by,
                "decided_by": item.decided_by,
                "reason": item.reason,
                "deployment_id": item.deployment_id,
                "created_at": item.created_at,
                "decided_at": item.decided_at,
            }
            for item in rows
        ]

    def _recent_switches(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = list(
            self._session.scalars(
                select(
                    StrategyRuntimeSwitchEntity
                )
                .order_by(
                    StrategyRuntimeSwitchEntity
                    .strategy_runtime_switch_id.desc()
                )
                .limit(limit)
            )
        )

        return [
            {
                "strategy_runtime_switch_id": (
                    item.strategy_runtime_switch_id
                ),
                "previous_deployment_id": (
                    item.previous_deployment_id
                ),
                "target_deployment_id": (
                    item.target_deployment_id
                ),
                "status_code": item.status_code,
                "requested_by": item.requested_by,
                "error_message": item.error_message,
                "created_at": item.created_at,
                "completed_at": item.completed_at,
            }
            for item in rows
        ]

    def _recent_pipelines(
        self,
        *,
        market_code: str,
        symbol: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        statement = select(
            StrategyDeploymentPipelineEntity
        ).where(
            StrategyDeploymentPipelineEntity.market_code
            == market_code
        )

        if symbol is None:
            statement = statement.where(
                StrategyDeploymentPipelineEntity
                .symbol.is_(None)
            )
        else:
            statement = statement.where(
                StrategyDeploymentPipelineEntity
                .symbol
                == symbol
            )

        rows = list(
            self._session.scalars(
                statement.order_by(
                    StrategyDeploymentPipelineEntity
                    .strategy_deployment_pipeline_id
                    .desc()
                )
                .limit(limit)
            )
        )

        return [
            {
                "strategy_deployment_pipeline_id": (
                    item
                    .strategy_deployment_pipeline_id
                ),
                "strategy_selection_run_id": (
                    item.strategy_selection_run_id
                ),
                "strategy_approval_run_id": (
                    item.strategy_approval_run_id
                ),
                "strategy_deployment_id": (
                    item.strategy_deployment_id
                ),
                "strategy_runtime_switch_id": (
                    item.strategy_runtime_switch_id
                ),
                "strategy_code": item.strategy_code,
                "status_code": item.status_code,
                "requested_by": item.requested_by,
                "message": item.message,
                "created_at": item.created_at,
                "completed_at": item.completed_at,
            }
            for item in rows
        ]

    def _recent_performance_checks(
        self,
        *,
        deployment_id: int | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        statement = select(
            StrategyDeploymentPerformanceEntity
        )

        if deployment_id is not None:
            statement = statement.where(
                StrategyDeploymentPerformanceEntity
                .strategy_deployment_id
                == deployment_id
            )

        rows = list(
            self._session.scalars(
                statement.order_by(
                    StrategyDeploymentPerformanceEntity
                    .strategy_deployment_performance_id
                    .desc()
                )
                .limit(limit)
            )
        )

        return [
            {
                "strategy_deployment_performance_id": (
                    item
                    .strategy_deployment_performance_id
                ),
                "strategy_deployment_id": (
                    item.strategy_deployment_id
                ),
                "strategy_code": item.strategy_code,
                "status_code": item.status_code,
                "total_trade_count": (
                    item.total_trade_count
                ),
                "total_return_rate": str(
                    item.total_return_rate
                ),
                "maximum_drawdown_rate": str(
                    item.maximum_drawdown_rate
                ),
                "win_rate": str(item.win_rate),
                "profit_factor": (
                    str(item.profit_factor)
                    if item.profit_factor is not None
                    else None
                ),
                "consecutive_losses": (
                    item.consecutive_losses
                ),
                "created_at": item.created_at,
            }
            for item in rows
        ]

    @staticmethod
    def _deployment_to_dict(
        item: StrategyDeploymentEntity,
    ) -> dict[str, Any]:
        return {
            "strategy_deployment_id": (
                item.strategy_deployment_id
            ),
            "strategy_code": item.strategy_code,
            "strategy_performance_run_id": (
                item.strategy_performance_run_id
            ),
            "market_code": item.market_code,
            "symbol": item.symbol,
            "mode_code": item.mode_code,
            "status_code": item.status_code,
            "parameter_payload": (
                item.parameter_payload
            ),
            "requested_by": item.requested_by,
            "activated_at": item.activated_at,
            "stopped_at": item.stopped_at,
            "replaced_by_deployment_id": (
                item.replaced_by_deployment_id
            ),
            "error_message": item.error_message,
            "created_at": item.created_at,
        }
