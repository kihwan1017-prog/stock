from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.policy_entities import (
    StrategyApprovalRunEntity,
)
from stock_platform.strategy_deployment.policy_models import (
    StrategyApprovalEvaluation,
    StrategyApprovalPolicy,
)


class StrategyApprovalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        selection_run_id: int,
        performance_run_id: int,
        strategy_code: str,
        market_code: str,
        symbol: str | None,
        evaluation: StrategyApprovalEvaluation,
        policy: StrategyApprovalPolicy,
        requested_by: str,
        automatic_approval: bool,
    ) -> StrategyApprovalRunEntity:
        entity = StrategyApprovalRunEntity(
            strategy_selection_run_id=selection_run_id,
            strategy_performance_run_id=performance_run_id,
            strategy_code=strategy_code,
            market_code=market_code.upper(),
            symbol=symbol.upper() if symbol else None,
            decision_code=evaluation.decision.value,
            status_code="EVALUATED",
            automatic_approval=automatic_approval,
            requested_by=requested_by,
            reason=evaluation.reason,
            policy_payload={
                "minimum_score": str(policy.minimum_score),
                "minimum_sharpe_ratio": str(
                    policy.minimum_sharpe_ratio
                ),
                "maximum_drawdown_rate": str(
                    policy.maximum_drawdown_rate
                ),
                "minimum_win_rate": str(
                    policy.minimum_win_rate
                ),
                "minimum_trade_count": (
                    policy.minimum_trade_count
                ),
                "minimum_confidence_score": str(
                    policy.minimum_confidence_score
                ),
                "require_walk_forward": (
                    policy.require_walk_forward
                ),
                "require_positive_return": (
                    policy.require_positive_return
                ),
                "require_kill_switch_inactive": (
                    policy.require_kill_switch_inactive
                ),
                "require_runtime_healthy": (
                    policy.require_runtime_healthy
                ),
            },
            check_payload=[
                {
                    "check_code": item.check_code,
                    "passed": item.passed,
                    "message": item.message,
                    "detail": item.detail,
                }
                for item in evaluation.checks
            ],
            decided_at=evaluation.evaluated_at,
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def get(
        self,
        approval_run_id: int,
    ) -> StrategyApprovalRunEntity | None:
        return self._session.get(
            StrategyApprovalRunEntity,
            approval_run_id,
        )

    def mark_deployed(
        self,
        *,
        entity: StrategyApprovalRunEntity,
        deployment_id: int,
        actor: str,
    ) -> None:
        entity.status_code = "DEPLOYED"
        entity.deployment_id = deployment_id
        entity.decided_by = actor
        entity.decided_at = datetime.now(timezone.utc)
        self._session.commit()

    def mark_failed(
        self,
        *,
        entity: StrategyApprovalRunEntity,
        actor: str,
        reason: str,
    ) -> None:
        entity.status_code = "FAILED"
        entity.decided_by = actor
        entity.reason = reason
        entity.decided_at = datetime.now(timezone.utc)
        self._session.commit()

    def history(
        self,
        *,
        limit: int = 100,
    ):
        return list(
            self._session.scalars(
                select(StrategyApprovalRunEntity)
                .order_by(
                    StrategyApprovalRunEntity
                    .strategy_approval_run_id.desc()
                )
                .limit(limit)
            )
        )
