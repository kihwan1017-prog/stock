from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.models import (
    StrategyDeploymentMode,
)
from stock_platform.strategy_deployment.registry import (
    StrategyFactoryRegistry,
)
from stock_platform.strategy_deployment.repository import (
    StrategyDeploymentRepository,
)
from stock_platform.strategy_deployment.runtime_models import (
    LoadedStrategyRuntime,
)


class ActiveStrategyRuntimeLoader:
    def __init__(
        self,
        *,
        session: Session,
        registry: StrategyFactoryRegistry,
    ) -> None:
        self._repository = StrategyDeploymentRepository(
            session
        )
        self._registry = registry

    def load(
        self,
        *,
        market_code: str,
        symbol: str | None,
        mode: StrategyDeploymentMode = (
            StrategyDeploymentMode.PAPER
        ),
    ) -> tuple[LoadedStrategyRuntime, object]:
        deployment = self._repository.get_active(
            market_code=market_code,
            symbol=symbol,
            mode_code=mode.value,
        )

        if deployment is None:
            raise LookupError(
                "Active strategy deployment not found"
            )

        strategy = self._registry.create(
            strategy_code=deployment.strategy_code,
            parameter_payload=(
                deployment.parameter_payload
            ),
        )

        runtime = LoadedStrategyRuntime(
            deployment_id=(
                deployment.strategy_deployment_id
            ),
            strategy_code=deployment.strategy_code,
            market_code=deployment.market_code,
            symbol=deployment.symbol,
            parameter_payload=(
                deployment.parameter_payload
            ),
            loaded_at=datetime.now(timezone.utc),
        )

        return runtime, strategy
