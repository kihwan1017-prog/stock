from __future__ import annotations

from stock_platform.strategy_deployment.runtime_manager import (
    dynamic_strategy_runtime_manager,
)


class DynamicRealtimeStrategyAdapter:
    """
    기존 Realtime Strategy Runner가 동적 전략을 호출할 수 있도록
    얇은 Adapter를 제공한다.
    """

    def evaluate(self, *args, **kwargs):
        strategy = (
            dynamic_strategy_runtime_manager
            .get_strategy()
        )

        evaluate = getattr(
            strategy,
            "evaluate",
            None,
        )

        if evaluate is None:
            raise TypeError(
                "Loaded strategy has no evaluate() method"
            )

        return evaluate(*args, **kwargs)

    def status(self):
        return (
            dynamic_strategy_runtime_manager.status()
        )
