from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.models import (
    StrategyDeploymentMode,
    StrategyDeploymentRequest,
    StrategyDeploymentResult,
    StrategyDeploymentStatus,
)
from stock_platform.strategy_deployment.repository import (
    StrategyDeploymentRepository,
)
from stock_platform.strategy_deployment.validation import (
    StrategyDeploymentValidator,
)


class PaperStrategyDeploymentService:
    """
    모의투자 전략을 안전하게 활성화하고 기존 전략을 교체한다.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = StrategyDeploymentRepository(
            session
        )
        self._validator = StrategyDeploymentValidator(
            session
        )

    def deploy(
        self,
        request: StrategyDeploymentRequest,
    ) -> StrategyDeploymentResult:
        if request.mode != StrategyDeploymentMode.PAPER:
            raise PermissionError(
                "STEP31-1 supports PAPER deployment only"
            )

        self._validator.validate_performance_run(
            performance_run_id=(
                request.strategy_performance_run_id
            ),
            strategy_code=request.strategy_code,
            market_code=request.market_code,
            symbol=request.symbol,
        )

        current = self._repository.get_active(
            market_code=request.market_code,
            symbol=request.symbol,
            mode_code=request.mode.value,
        )

        deployment = self._repository.create(
            strategy_code=request.strategy_code,
            strategy_performance_run_id=(
                request.strategy_performance_run_id
            ),
            market_code=request.market_code,
            symbol=request.symbol,
            mode_code=request.mode.value,
            parameter_payload=request.parameter_payload,
            requested_by=request.requested_by,
        )

        try:
            now = datetime.now(timezone.utc)

            if current is not None:
                current.status_code = (
                    StrategyDeploymentStatus.REPLACED.value
                )
                current.stopped_at = now
                current.replaced_by_deployment_id = (
                    deployment.strategy_deployment_id
                )

                self._repository.add_history(
                    deployment_id=current.strategy_deployment_id,
                    action_code="REPLACED",
                    actor=request.requested_by,
                    message=(
                        "Active paper strategy replaced by "
                        f"{request.strategy_code}"
                    ),
                    detail_payload={
                        "replacement_deployment_id": (
                            deployment
                            .strategy_deployment_id
                        )
                    },
                )

            deployment.status_code = (
                StrategyDeploymentStatus.ACTIVE.value
            )
            deployment.activated_at = now
            self._session.commit()
            self._session.refresh(deployment)

            self._repository.add_history(
                deployment_id=(
                    deployment.strategy_deployment_id
                ),
                action_code="ACTIVATE",
                actor=request.requested_by,
                message="Paper strategy activated",
                detail_payload={
                    "strategy_code": request.strategy_code,
                    "performance_run_id": (
                        request.strategy_performance_run_id
                    ),
                },
            )

            return StrategyDeploymentResult(
                strategy_deployment_id=(
                    deployment.strategy_deployment_id
                ),
                strategy_code=deployment.strategy_code,
                strategy_performance_run_id=(
                    deployment
                    .strategy_performance_run_id
                ),
                status=StrategyDeploymentStatus.ACTIVE,
                mode=StrategyDeploymentMode.PAPER,
                activated_at=deployment.activated_at,
                message="Paper strategy deployment completed",
            )

        except Exception as exc:
            self._session.rollback()
            deployment.status_code = (
                StrategyDeploymentStatus.FAILED.value
            )
            deployment.error_message = str(exc)
            self._session.commit()
            raise

    def stop(
        self,
        *,
        deployment_id: int,
        actor: str,
        reason: str,
    ) -> StrategyDeploymentResult:
        deployment = self._repository.get(
            deployment_id
        )

        if deployment is None:
            raise LookupError(
                "Strategy deployment not found"
            )

        if deployment.status_code != "ACTIVE":
            raise ValueError(
                "Only ACTIVE deployment can be stopped"
            )

        deployment.status_code = (
            StrategyDeploymentStatus.STOPPED.value
        )
        deployment.stopped_at = datetime.now(
            timezone.utc
        )
        self._session.commit()

        self._repository.add_history(
            deployment_id=deployment_id,
            action_code="STOP",
            actor=actor,
            message=reason,
        )

        return StrategyDeploymentResult(
            strategy_deployment_id=deployment_id,
            strategy_code=deployment.strategy_code,
            strategy_performance_run_id=(
                deployment.strategy_performance_run_id
            ),
            status=StrategyDeploymentStatus.STOPPED,
            mode=StrategyDeploymentMode(
                deployment.mode_code
            ),
            activated_at=deployment.activated_at,
            message=reason,
        )

    def update_parameters(
        self,
        *,
        deployment_id: int,
        parameter_payload: dict[str, Any],
        requested_by: str,
    ) -> StrategyDeploymentResult:
        """활성 전략 파라미터를 새 배포로 교체(즉시 ACTIVE)."""

        current = self._repository.get(deployment_id)
        if current is None:
            raise LookupError(
                "Strategy deployment not found"
            )
        if current.status_code != "ACTIVE":
            raise ValueError(
                "Only ACTIVE deployment can be updated"
            )

        return self.deploy(
            StrategyDeploymentRequest(
                strategy_code=current.strategy_code,
                strategy_performance_run_id=(
                    current.strategy_performance_run_id
                ),
                market_code=current.market_code,
                symbol=current.symbol,
                mode=StrategyDeploymentMode(
                    current.mode_code
                ),
                parameter_payload=parameter_payload,
                requested_by=requested_by,
            )
        )
