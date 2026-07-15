from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.performance.entities import (
    StrategyPerformanceMetricEntity,
    StrategyPerformanceRunEntity,
)
from stock_platform.performance.selector_entities import (
    StrategySelectionRunEntity,
)
from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)
from stock_platform.strategy_deployment.policy_models import (
    StrategyApprovalCheck,
    StrategyApprovalDecision,
    StrategyApprovalEvaluation,
    StrategyApprovalPolicy,
)
from stock_platform.strategy_deployment.runtime_manager import (
    dynamic_strategy_runtime_manager,
)


class StrategyApprovalPolicyService:
    def __init__(
        self,
        *,
        session: Session,
        policy: StrategyApprovalPolicy | None = None,
    ) -> None:
        self._session = session
        self._policy = policy or StrategyApprovalPolicy()

    def evaluate(
        self,
        *,
        selection_run_id: int,
    ) -> StrategyApprovalEvaluation:
        selection = self._session.get(
            StrategySelectionRunEntity,
            selection_run_id,
        )

        if selection is None:
            raise LookupError(
                "Strategy selection run not found"
            )

        performance_run = self._session.get(
            StrategyPerformanceRunEntity,
            selection.selected_performance_run_id,
        )

        if performance_run is None:
            raise LookupError(
                "Strategy performance run not found"
            )

        metric = self._session.query(
            StrategyPerformanceMetricEntity
        ).filter(
            StrategyPerformanceMetricEntity
            .strategy_performance_run_id
            == performance_run.strategy_performance_run_id
        ).one_or_none()

        if metric is None:
            raise LookupError(
                "Strategy performance metric not found"
            )

        checks: list[StrategyApprovalCheck] = []

        self._append(
            checks,
            "SELECTION_CONFIDENCE",
            Decimal(selection.confidence_score)
            >= self._policy.minimum_confidence_score,
            "LLM confidence threshold",
            {
                "actual": str(selection.confidence_score),
                "minimum": str(
                    self._policy.minimum_confidence_score
                ),
            },
        )

        self._append(
            checks,
            "RUN_TYPE",
            (
                not self._policy.require_walk_forward
                or performance_run.run_type
                == "WALK_FORWARD"
            ),
            "Walk Forward performance required",
            {"run_type": performance_run.run_type},
        )

        self._append(
            checks,
            "POSITIVE_RETURN",
            (
                not self._policy.require_positive_return
                or Decimal(metric.total_return_rate) > 0
            ),
            "Positive total return required",
            {
                "total_return_rate": str(
                    metric.total_return_rate
                )
            },
        )

        self._append(
            checks,
            "SHARPE_RATIO",
            (
                metric.sharpe_ratio is not None
                and Decimal(metric.sharpe_ratio)
                >= self._policy.minimum_sharpe_ratio
            ),
            "Sharpe ratio threshold",
            {
                "actual": (
                    str(metric.sharpe_ratio)
                    if metric.sharpe_ratio is not None
                    else None
                ),
                "minimum": str(
                    self._policy.minimum_sharpe_ratio
                ),
            },
        )

        self._append(
            checks,
            "MAXIMUM_DRAWDOWN",
            Decimal(metric.maximum_drawdown_rate)
            <= self._policy.maximum_drawdown_rate,
            "Maximum drawdown threshold",
            {
                "actual": str(
                    metric.maximum_drawdown_rate
                ),
                "maximum": str(
                    self._policy.maximum_drawdown_rate
                ),
            },
        )

        self._append(
            checks,
            "WIN_RATE",
            Decimal(metric.win_rate)
            >= self._policy.minimum_win_rate,
            "Win rate threshold",
            {
                "actual": str(metric.win_rate),
                "minimum": str(
                    self._policy.minimum_win_rate
                ),
            },
        )

        self._append(
            checks,
            "TRADE_COUNT",
            metric.total_trade_count
            >= self._policy.minimum_trade_count,
            "Minimum trade count threshold",
            {
                "actual": metric.total_trade_count,
                "minimum": (
                    self._policy.minimum_trade_count
                ),
            },
        )

        kill_switch_active = KillSwitchService(
            self._session
        ).is_active()

        self._append(
            checks,
            "KILL_SWITCH",
            (
                not self._policy.require_kill_switch_inactive
                or not kill_switch_active
            ),
            "Kill Switch must be inactive",
            {"active": kill_switch_active},
        )

        runtime_status = (
            dynamic_strategy_runtime_manager.status()
        )
        runtime_healthy = (
            runtime_status.get("last_error") is None
        )

        self._append(
            checks,
            "RUNTIME_HEALTH",
            (
                not self._policy.require_runtime_healthy
                or runtime_healthy
            ),
            "Strategy runtime must be healthy",
            runtime_status,
        )

        passed = all(item.passed for item in checks)

        return StrategyApprovalEvaluation(
            decision=(
                StrategyApprovalDecision.APPROVED
                if passed
                else StrategyApprovalDecision.REJECTED
            ),
            checks=checks,
            evaluated_at=datetime.now(timezone.utc),
            reason=(
                "All approval policy checks passed"
                if passed
                else "One or more approval policy checks failed"
            ),
        )

    @staticmethod
    def _append(
        checks,
        code,
        passed,
        message,
        detail,
    ) -> None:
        checks.append(
            StrategyApprovalCheck(
                check_code=code,
                passed=passed,
                message=message,
                detail=detail,
            )
        )
