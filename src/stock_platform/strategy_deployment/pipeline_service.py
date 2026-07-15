from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.performance.selector_repository import (
    StrategySelectionRepository,
)
from stock_platform.strategy_deployment.automation_service import (
    StrategyAutoDeploymentService,
)
from stock_platform.strategy_deployment.pipeline_models import (
    StrategyDeploymentPipelineResult,
    StrategyDeploymentPipelineStatus,
)
from stock_platform.strategy_deployment.pipeline_repository import (
    StrategyDeploymentPipelineRepository,
)
from stock_platform.strategy_deployment.policy_models import (
    StrategyApprovalDecision,
)
from stock_platform.strategy_deployment.switch_service import (
    SafeStrategyRuntimeSwitchService,
)


class EndToEndStrategyDeploymentPipeline:
    """
    최신 전략 선택 → 승인정책 → PAPER 배치 → Dry Run →
    상태 이전 → Runtime 교체 → 실패 시 Rollback을 한 번에 수행한다.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._pipeline_repository = (
            StrategyDeploymentPipelineRepository(session)
        )

    async def run(
        self,
        *,
        market_code: str,
        symbol: str | None,
        requested_by: str,
        sample_context: dict[str, Any] | None = None,
        allow_auto_deploy: bool = False,
    ) -> StrategyDeploymentPipelineResult:
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

        pipeline = self._pipeline_repository.start(
            selection_run_id=(
                selection.strategy_selection_run_id
            ),
            market_code=market_code,
            symbol=symbol,
            requested_by=requested_by,
        )

        approval = None
        deployment_id = None

        try:
            approval = StrategyAutoDeploymentService(
                session=self._session
            ).evaluate_latest(
                market_code=market_code,
                symbol=symbol,
                requested_by=requested_by,
                auto_deploy=allow_auto_deploy,
            )

            if approval.decision_code != (
                StrategyApprovalDecision.APPROVED.value
            ):
                self._pipeline_repository.finish(
                    entity=pipeline,
                    status_code="APPROVAL_REJECTED",
                    message="Strategy approval policy rejected deployment",
                    detail_payload={
                        "approval_reason": approval.reason,
                        "checks": approval.check_payload,
                    },
                    approval_run_id=(
                        approval.strategy_approval_run_id
                    ),
                    strategy_code=approval.strategy_code,
                )

                return StrategyDeploymentPipelineResult(
                    status=(
                        StrategyDeploymentPipelineStatus
                        .APPROVAL_REJECTED
                    ),
                    approval_run_id=(
                        approval.strategy_approval_run_id
                    ),
                    deployment_id=None,
                    switch_status=None,
                    strategy_code=approval.strategy_code,
                    message=(
                        "Strategy approval policy rejected deployment"
                    ),
                    detail={
                        "approval_reason": approval.reason,
                        "checks": approval.check_payload,
                    },
                    completed_at=datetime.now(timezone.utc),
                )

            if not allow_auto_deploy:
                self._pipeline_repository.finish(
                    entity=pipeline,
                    status_code="DEPLOYED",
                    message=(
                        "Approval passed; automatic deployment "
                        "is disabled"
                    ),
                    detail_payload={
                        "approval_only": True,
                    },
                    approval_run_id=(
                        approval.strategy_approval_run_id
                    ),
                    strategy_code=approval.strategy_code,
                )

                return StrategyDeploymentPipelineResult(
                    status=(
                        StrategyDeploymentPipelineStatus.DEPLOYED
                    ),
                    approval_run_id=(
                        approval.strategy_approval_run_id
                    ),
                    deployment_id=None,
                    switch_status=None,
                    strategy_code=approval.strategy_code,
                    message=(
                        "Approval passed; automatic deployment "
                        "is disabled"
                    ),
                    detail={"approval_only": True},
                    completed_at=datetime.now(timezone.utc),
                )

            deployment_id = approval.deployment_id

            if deployment_id is None:
                raise RuntimeError(
                    "Approved strategy was not deployed"
                )

            switch_result = await (
                SafeStrategyRuntimeSwitchService(
                    self._session
                ).switch(
                    target_deployment_id=deployment_id,
                    requested_by=requested_by,
                    sample_context=sample_context or {},
                )
            )

            status = (
                StrategyDeploymentPipelineStatus.SWITCHED
                if switch_result.status.value == "SWITCHED"
                else StrategyDeploymentPipelineStatus.ROLLED_BACK
            )

            self._pipeline_repository.finish(
                entity=pipeline,
                status_code=status.value,
                message=switch_result.message,
                detail_payload={
                    "switch_status": switch_result.status.value,
                    "previous_deployment_id": (
                        switch_result.previous_deployment_id
                    ),
                    "current_deployment_id": (
                        switch_result.current_deployment_id
                    ),
                },
                approval_run_id=(
                    approval.strategy_approval_run_id
                ),
                deployment_id=deployment_id,
                strategy_code=approval.strategy_code,
            )

            return StrategyDeploymentPipelineResult(
                status=status,
                approval_run_id=(
                    approval.strategy_approval_run_id
                ),
                deployment_id=deployment_id,
                switch_status=switch_result.status.value,
                strategy_code=approval.strategy_code,
                message=switch_result.message,
                detail={
                    "previous_deployment_id": (
                        switch_result.previous_deployment_id
                    ),
                    "current_deployment_id": (
                        switch_result.current_deployment_id
                    ),
                },
                completed_at=datetime.now(timezone.utc),
            )

        except Exception as exc:
            self._session.rollback()

            self._pipeline_repository.finish(
                entity=pipeline,
                status_code="FAILED",
                message=str(exc),
                detail_payload={
                    "error": str(exc),
                },
                approval_run_id=(
                    approval.strategy_approval_run_id
                    if approval is not None
                    else None
                ),
                deployment_id=deployment_id,
                strategy_code=(
                    approval.strategy_code
                    if approval is not None
                    else selection.selected_strategy_code
                ),
            )

            return StrategyDeploymentPipelineResult(
                status=StrategyDeploymentPipelineStatus.FAILED,
                approval_run_id=(
                    approval.strategy_approval_run_id
                    if approval is not None
                    else None
                ),
                deployment_id=deployment_id,
                switch_status=None,
                strategy_code=(
                    approval.strategy_code
                    if approval is not None
                    else selection.selected_strategy_code
                ),
                message=str(exc),
                detail={"error": str(exc)},
                completed_at=datetime.now(timezone.utc),
            )
