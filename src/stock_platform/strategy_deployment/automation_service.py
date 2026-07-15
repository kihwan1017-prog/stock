from __future__ import annotations

from sqlalchemy.orm import Session

from stock_platform.performance.selector_repository import (
    StrategySelectionRepository,
)
from stock_platform.strategy_deployment.models import (
    StrategyDeploymentMode,
    StrategyDeploymentRequest,
)
from stock_platform.strategy_deployment.policy_models import (
    StrategyApprovalDecision,
    StrategyApprovalPolicy,
)
from stock_platform.strategy_deployment.policy_repository import (
    StrategyApprovalRepository,
)
from stock_platform.strategy_deployment.policy_service import (
    StrategyApprovalPolicyService,
)
from stock_platform.strategy_deployment.service import (
    PaperStrategyDeploymentService,
)


class StrategyAutoDeploymentService:
    def __init__(
        self,
        *,
        session: Session,
        policy: StrategyApprovalPolicy | None = None,
    ) -> None:
        self._session = session
        self._policy = policy or StrategyApprovalPolicy()
        self._approvals = StrategyApprovalRepository(
            session
        )

    def evaluate_latest(
        self,
        *,
        market_code: str,
        symbol: str | None,
        requested_by: str = "SYSTEM",
        auto_deploy: bool = False,
    ):
        selection = StrategySelectionRepository(
            self._session
        ).latest(
            market_code=market_code,
            symbol=symbol,
        )

        if selection is None:
            raise LookupError(
                "Latest strategy selection not found"
            )

        evaluation = StrategyApprovalPolicyService(
            session=self._session,
            policy=self._policy,
        ).evaluate(
            selection_run_id=(
                selection.strategy_selection_run_id
            )
        )

        approval = self._approvals.create(
            selection_run_id=(
                selection.strategy_selection_run_id
            ),
            performance_run_id=(
                selection.selected_performance_run_id
            ),
            strategy_code=(
                selection.selected_strategy_code
            ),
            market_code=selection.market_code,
            symbol=selection.symbol,
            evaluation=evaluation,
            policy=self._policy,
            requested_by=requested_by,
            automatic_approval=auto_deploy,
        )

        if (
            auto_deploy
            and evaluation.decision
            == StrategyApprovalDecision.APPROVED
        ):
            deployment = PaperStrategyDeploymentService(
                self._session
            ).deploy(
                StrategyDeploymentRequest(
                    strategy_code=(
                        selection.selected_strategy_code
                    ),
                    strategy_performance_run_id=(
                        selection
                        .selected_performance_run_id
                    ),
                    market_code=selection.market_code,
                    symbol=selection.symbol,
                    mode=StrategyDeploymentMode.PAPER,
                    parameter_payload={},
                    requested_by=requested_by,
                )
            )

            self._approvals.mark_deployed(
                entity=approval,
                deployment_id=(
                    deployment.strategy_deployment_id
                ),
                actor=requested_by,
            )

        return approval

    def force_deploy(
        self,
        *,
        approval_run_id: int,
        actor: str,
    ):
        approval = self._approvals.get(
            approval_run_id
        )

        if approval is None:
            raise LookupError(
                "Strategy approval run not found"
            )

        deployment = PaperStrategyDeploymentService(
            self._session
        ).deploy(
            StrategyDeploymentRequest(
                strategy_code=approval.strategy_code,
                strategy_performance_run_id=(
                    approval.strategy_performance_run_id
                ),
                market_code=approval.market_code,
                symbol=approval.symbol,
                mode=StrategyDeploymentMode.PAPER,
                parameter_payload={},
                requested_by=actor,
            )
        )

        approval.decision_code = (
            StrategyApprovalDecision.FORCED.value
        )
        self._approvals.mark_deployed(
            entity=approval,
            deployment_id=(
                deployment.strategy_deployment_id
            ),
            actor=actor,
        )
        return approval

    def reject(
        self,
        *,
        approval_run_id: int,
        actor: str,
        reason: str,
    ):
        approval = self._approvals.get(
            approval_run_id
        )

        if approval is None:
            raise LookupError(
                "Strategy approval run not found"
            )

        approval.decision_code = (
            StrategyApprovalDecision.REJECTED.value
        )
        approval.reason = reason
        approval.decided_by = actor
        self._session.commit()
        return approval
