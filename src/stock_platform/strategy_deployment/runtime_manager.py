from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from stock_platform.database.session import (
    get_session_factory,
)
from stock_platform.strategy_deployment.default_registry import (
    configure_default_strategy_registry,
)
from stock_platform.strategy_deployment.models import (
    StrategyDeploymentMode,
)
from stock_platform.strategy_deployment.registry import (
    strategy_factory_registry,
)
from stock_platform.strategy_deployment.runtime_loader import (
    ActiveStrategyRuntimeLoader,
)
from stock_platform.strategy_deployment.runtime_models import (
    LoadedStrategyRuntime,
    StrategyRuntimeReloadResult,
)


class DynamicStrategyRuntimeManager:
    """
    활성 배치 전략을 DB에서 읽고 메모리의 실시간 전략 인스턴스를
    안전하게 교체한다.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._runtime: LoadedStrategyRuntime | None = None
        self._strategy: object | None = None
        self._last_error: str | None = None

    async def initialize(
        self,
        *,
        market_code: str,
        symbol: str | None,
    ) -> StrategyRuntimeReloadResult:
        configure_default_strategy_registry()

        return await self.reload(
            market_code=market_code,
            symbol=symbol,
            force=True,
        )

    async def reload(
        self,
        *,
        market_code: str,
        symbol: str | None,
        force: bool = False,
    ) -> StrategyRuntimeReloadResult:
        async with self._lock:
            previous_id = (
                self._runtime.deployment_id
                if self._runtime is not None
                else None
            )

            session = get_session_factory()()

            try:
                runtime, strategy = (
                    ActiveStrategyRuntimeLoader(
                        session=session,
                        registry=strategy_factory_registry,
                    ).load(
                        market_code=market_code,
                        symbol=symbol,
                        mode=StrategyDeploymentMode.PAPER,
                    )
                )

                if (
                    not force
                    and previous_id
                    == runtime.deployment_id
                ):
                    return StrategyRuntimeReloadResult(
                        changed=False,
                        previous_deployment_id=previous_id,
                        current_deployment_id=previous_id,
                        strategy_code=runtime.strategy_code,
                        message=(
                            "Active deployment has not changed"
                        ),
                        reloaded_at=datetime.now(
                            timezone.utc
                        ),
                    )

                self._runtime = runtime
                self._strategy = strategy
                self._last_error = None

                return StrategyRuntimeReloadResult(
                    changed=True,
                    previous_deployment_id=previous_id,
                    current_deployment_id=(
                        runtime.deployment_id
                    ),
                    strategy_code=runtime.strategy_code,
                    message=(
                        "Realtime strategy runtime reloaded"
                    ),
                    reloaded_at=datetime.now(
                        timezone.utc
                    ),
                )

            except Exception as exc:
                self._last_error = str(exc)
                raise
            finally:
                session.close()

    async def clear(self) -> None:
        async with self._lock:
            self._runtime = None
            self._strategy = None

    def get_strategy(self):
        if self._strategy is None:
            raise LookupError(
                "Realtime strategy is not loaded"
            )
        return self._strategy

    def status(self) -> dict[str, Any]:
        return {
            "loaded": self._runtime is not None,
            "runtime": self._runtime,
            "registered_strategy_codes": (
                strategy_factory_registry.list_codes()
            ),
            "last_error": self._last_error,
        }


dynamic_strategy_runtime_manager = (
    DynamicStrategyRuntimeManager()
)
