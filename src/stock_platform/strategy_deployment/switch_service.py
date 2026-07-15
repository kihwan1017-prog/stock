from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.dry_run import StrategyDryRunService
from stock_platform.strategy_deployment.registry import strategy_factory_registry
from stock_platform.strategy_deployment.repository import StrategyDeploymentRepository
from stock_platform.strategy_deployment.runtime_manager import dynamic_strategy_runtime_manager
from stock_platform.strategy_deployment.runtime_models import LoadedStrategyRuntime
from stock_platform.strategy_deployment.state_transfer import StrategyStateTransferService
from stock_platform.strategy_deployment.switch_models import (
    StrategySwitchResult,
    StrategySwitchStatus,
)
from stock_platform.strategy_deployment.switch_repository import (
    StrategyRuntimeSwitchRepository,
)


class SafeStrategyRuntimeSwitchService:
    """
    1. 대상 배치 조회
    2. Dry Run
    3. 기존 상태 백업
    4. 새 전략 생성
    5. 상태 이전
    6. Runtime 교체
    7. 실패 시 이전 전략 복원
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._deployments = StrategyDeploymentRepository(
            session
        )
        self._switches = StrategyRuntimeSwitchRepository(
            session
        )

    async def switch(
        self,
        *,
        target_deployment_id: int,
        requested_by: str,
        sample_context: dict | None = None,
    ) -> StrategySwitchResult:
        target = self._deployments.get(
            target_deployment_id
        )

        if target is None:
            raise LookupError(
                "Target strategy deployment not found"
            )

        if target.status_code != "ACTIVE":
            raise ValueError(
                "Target deployment must be ACTIVE"
            )

        previous_runtime = (
            dynamic_strategy_runtime_manager
            ._runtime
        )
        previous_strategy = (
            dynamic_strategy_runtime_manager
            ._strategy
        )

        target_strategy = strategy_factory_registry.create(
            strategy_code=target.strategy_code,
            parameter_payload=target.parameter_payload,
        )
        target_runtime = LoadedStrategyRuntime(
            deployment_id=target.strategy_deployment_id,
            strategy_code=target.strategy_code,
            market_code=target.market_code,
            symbol=target.symbol,
            parameter_payload=target.parameter_payload,
            loaded_at=datetime.now(timezone.utc),
        )

        dry_run = StrategyDryRunService().run(
            runtime=target_runtime,
            strategy=target_strategy,
            sample_context=sample_context,
        )

        previous_state = (
            StrategyStateTransferService.export_state(
                previous_strategy
            )
            if previous_strategy is not None
            else {}
        )

        switch_entity = self._switches.create(
            previous_deployment_id=(
                previous_runtime.deployment_id
                if previous_runtime is not None
                else None
            ),
            target_deployment_id=target_deployment_id,
            requested_by=requested_by,
            status_code=(
                "DRY_RUN_PASSED"
                if dry_run.passed
                else "DRY_RUN_FAILED"
            ),
            dry_run_payload={
                "passed": dry_run.passed,
                "checks": dry_run.checks,
            },
            previous_state_payload=previous_state,
        )

        if not dry_run.passed:
            self._switches.complete(
                entity=switch_entity,
                status_code="DRY_RUN_FAILED",
                target_state_payload={},
                completed_at=datetime.now(timezone.utc),
            )
            return StrategySwitchResult(
                status=StrategySwitchStatus.DRY_RUN_FAILED,
                previous_deployment_id=(
                    previous_runtime.deployment_id
                    if previous_runtime is not None
                    else None
                ),
                current_deployment_id=(
                    previous_runtime.deployment_id
                    if previous_runtime is not None
                    else None
                ),
                strategy_code=(
                    previous_runtime.strategy_code
                    if previous_runtime is not None
                    else None
                ),
                message="Dry Run failed; runtime was not changed",
                completed_at=datetime.now(timezone.utc),
            )

        try:
            StrategyStateTransferService.import_state(
                target_strategy,
                previous_state,
            )

            async with dynamic_strategy_runtime_manager._lock:
                dynamic_strategy_runtime_manager._runtime = (
                    target_runtime
                )
                dynamic_strategy_runtime_manager._strategy = (
                    target_strategy
                )
                dynamic_strategy_runtime_manager._last_error = None

            target_state = (
                StrategyStateTransferService.export_state(
                    target_strategy
                )
            )

            self._switches.complete(
                entity=switch_entity,
                status_code="SWITCHED",
                target_state_payload=target_state,
                completed_at=datetime.now(timezone.utc),
            )

            return StrategySwitchResult(
                status=StrategySwitchStatus.SWITCHED,
                previous_deployment_id=(
                    previous_runtime.deployment_id
                    if previous_runtime is not None
                    else None
                ),
                current_deployment_id=(
                    target_runtime.deployment_id
                ),
                strategy_code=target_runtime.strategy_code,
                message="Strategy runtime switched successfully",
                completed_at=datetime.now(timezone.utc),
            )

        except Exception as exc:
            async with dynamic_strategy_runtime_manager._lock:
                dynamic_strategy_runtime_manager._runtime = (
                    previous_runtime
                )
                dynamic_strategy_runtime_manager._strategy = (
                    previous_strategy
                )
                dynamic_strategy_runtime_manager._last_error = (
                    str(exc)
                )

            self._switches.complete(
                entity=switch_entity,
                status_code="ROLLED_BACK",
                target_state_payload={},
                completed_at=datetime.now(timezone.utc),
                error_message=str(exc),
            )

            return StrategySwitchResult(
                status=StrategySwitchStatus.ROLLED_BACK,
                previous_deployment_id=(
                    previous_runtime.deployment_id
                    if previous_runtime is not None
                    else None
                ),
                current_deployment_id=(
                    previous_runtime.deployment_id
                    if previous_runtime is not None
                    else None
                ),
                strategy_code=(
                    previous_runtime.strategy_code
                    if previous_runtime is not None
                    else None
                ),
                message=(
                    "Strategy switch failed and previous "
                    "runtime was restored"
                ),
                completed_at=datetime.now(timezone.utc),
            )
