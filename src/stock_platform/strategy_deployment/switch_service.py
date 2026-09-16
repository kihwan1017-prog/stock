"""STEP 8-5-5 — Safe Strategy Runtime Switch (Scope 기반)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.dry_run import StrategyDryRunService
from stock_platform.strategy_deployment.registry import strategy_factory_registry
from stock_platform.strategy_deployment.repository import (
    StrategyDeploymentRepository,
)
from stock_platform.strategy_deployment.runtime_manager import (
    ScopedRuntimeEntry,
    dynamic_strategy_runtime_manager,
)
from stock_platform.strategy_deployment.runtime_models import (
    LoadedStrategyRuntime,
)
from stock_platform.strategy_deployment.runtime_scope import (
    RuntimeLifecycleStatus,
)
from stock_platform.strategy_deployment.state_transfer import (
    StrategyStateTransferService,
)
from stock_platform.strategy_deployment.switch_models import (
    StrategySwitchResult,
    StrategySwitchStatus,
)
from stock_platform.strategy_deployment.switch_repository import (
    StrategyRuntimeSwitchRepository,
)


class SafeStrategyRuntimeSwitchService:
    """대상 Scope의 Runtime만 교체한다. 전역 슬롯 사용 금지."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._deployments = StrategyDeploymentRepository(session)
        self._switches = StrategyRuntimeSwitchRepository(session)

    async def switch(
        self,
        *,
        target_deployment_id: int,
        requested_by: str,
        sample_context: dict | None = None,
        scope_key: str | None = None,
        user_id: int | None = None,
        paper_account_id: int | None = None,
        user_broker_account_id: int | None = None,
    ) -> StrategySwitchResult:
        target = self._deployments.get(target_deployment_id)
        if target is None:
            raise LookupError("Target strategy deployment not found")
        if target.status_code != "ACTIVE":
            raise ValueError("Target deployment must be ACTIVE")

        if not scope_key:
            raise ValueError(
                "scope_key is required; global runtime switch removed (STEP 8-5-5)"
            )

        entry = dynamic_strategy_runtime_manager.get_entry(scope_key)
        if entry is None:
            raise LookupError(f"Runtime not found for scope: {scope_key}")

        # 계좌 일치 검증 (변조 차단)
        if user_id is not None and entry.scope.user_id != int(user_id):
            raise PermissionError("Scope user mismatch")
        if (
            paper_account_id is not None
            and entry.scope.paper_account_id != int(paper_account_id)
        ):
            raise PermissionError("Scope paper account mismatch")
        if (
            user_broker_account_id is not None
            and entry.scope.user_broker_account_id
            != int(user_broker_account_id)
        ):
            raise PermissionError("Scope UBA mismatch")

        previous_runtime = entry.runtime
        previous_strategy = entry.strategy
        scope = entry.scope

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
            user_id=scope.user_id,
            account_id=scope.paper_account_id,
            user_broker_account_id=scope.user_broker_account_id,
            strategy_id=scope.strategy_id,
            strategy_version=scope.strategy_version,
            market_type=scope.market_type,
            scope_key=scope.scope_key,
            broker_code=scope.broker_code,
            account_kind=scope.account_kind.value,
        )

        dry_run = StrategyDryRunService().run(
            runtime=target_runtime,
            strategy=target_strategy,
            sample_context=sample_context,
        )
        previous_state = (
            StrategyStateTransferService.export_state(previous_strategy)
            if previous_strategy is not None
            else {}
        )

        switch_entity = self._switches.create(
            previous_deployment_id=previous_runtime.deployment_id,
            target_deployment_id=target_deployment_id,
            requested_by=requested_by,
            status_code=(
                "DRY_RUN_PASSED" if dry_run.passed else "DRY_RUN_FAILED"
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
                previous_deployment_id=previous_runtime.deployment_id,
                current_deployment_id=previous_runtime.deployment_id,
                strategy_code=previous_runtime.strategy_code,
                message="Dry Run failed; runtime was not changed",
                completed_at=datetime.now(timezone.utc),
            )

        try:
            StrategyStateTransferService.import_state(
                target_strategy, previous_state
            )
            new_entry = ScopedRuntimeEntry(
                scope=scope,
                runtime=target_runtime,
                strategy=target_strategy,
                status=entry.status,
                pause_reason=entry.pause_reason,
                last_started_at=entry.last_started_at,
            )
            await dynamic_strategy_runtime_manager.put_entry(new_entry)

            target_state = StrategyStateTransferService.export_state(
                target_strategy
            )
            self._switches.complete(
                entity=switch_entity,
                status_code="SWITCHED",
                target_state_payload=target_state,
                completed_at=datetime.now(timezone.utc),
            )
            return StrategySwitchResult(
                status=StrategySwitchStatus.SWITCHED,
                previous_deployment_id=previous_runtime.deployment_id,
                current_deployment_id=target_runtime.deployment_id,
                strategy_code=target_runtime.strategy_code,
                message="Strategy runtime switched successfully",
                completed_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            await dynamic_strategy_runtime_manager.put_entry(
                ScopedRuntimeEntry(
                    scope=scope,
                    runtime=previous_runtime,
                    strategy=previous_strategy,
                    status=RuntimeLifecycleStatus.ERROR,
                    last_error=str(exc),
                    pause_reason=entry.pause_reason,
                )
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
                previous_deployment_id=previous_runtime.deployment_id,
                current_deployment_id=previous_runtime.deployment_id,
                strategy_code=previous_runtime.strategy_code,
                message=(
                    "Strategy switch failed and previous "
                    "runtime was restored"
                ),
                completed_at=datetime.now(timezone.utc),
            )
