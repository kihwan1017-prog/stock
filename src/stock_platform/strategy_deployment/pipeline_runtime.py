from __future__ import annotations

import os
from typing import Any

from stock_platform.database.session import (
    get_session_factory,
)
from stock_platform.strategy_deployment.pipeline_service import (
    EndToEndStrategyDeploymentPipeline,
)


class StrategyDeploymentPipelineManager:
    def __init__(self) -> None:
        self._running = False
        self._last_result = None
        self._last_error: str | None = None

    async def run(
        self,
        *,
        market_code: str,
        symbol: str | None,
        requested_by: str,
        sample_context: dict[str, Any] | None = None,
        allow_auto_deploy: bool | None = None,
    ):
        if self._running:
            raise ValueError(
                "Strategy deployment pipeline is already running"
            )

        self._running = True
        self._last_error = None

        session = get_session_factory()()

        try:
            auto_deploy = (
                allow_auto_deploy
                if allow_auto_deploy is not None
                else (
                    os.getenv(
                        "STRATEGY_AUTO_DEPLOY_ENABLED",
                        "false",
                    ).lower()
                    == "true"
                )
            )

            result = await EndToEndStrategyDeploymentPipeline(
                session
            ).run(
                market_code=market_code,
                symbol=symbol,
                requested_by=requested_by,
                sample_context=sample_context or {},
                allow_auto_deploy=auto_deploy,
            )
            self._last_result = result
            return result

        except Exception as exc:
            self._last_error = str(exc)
            raise
        finally:
            session.close()
            self._running = False

    def status(self):
        return {
            "running": self._running,
            "last_result": self._last_result,
            "last_error": self._last_error,
        }


strategy_deployment_pipeline_manager = (
    StrategyDeploymentPipelineManager()
)
