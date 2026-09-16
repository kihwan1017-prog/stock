from __future__ import annotations

from stock_platform.strategy_deployment.runtime_manager import (
    RuntimeScopeRequiredError,
    dynamic_strategy_runtime_manager,
)


class DynamicRealtimeStrategyAdapter:
    """Scope별 동적 전략 평가 Adapter — scope_key 필수."""

    def evaluate(self, *args, scope_key: str | None = None, **kwargs):
        if not scope_key:
            raise RuntimeScopeRequiredError(
                "scope_key is required for strategy evaluate (STEP 8-5-5)"
            )
        strategy = dynamic_strategy_runtime_manager.get_strategy(
            scope_key=scope_key
        )
        evaluate = getattr(strategy, "evaluate", None)
        if evaluate is None:
            raise TypeError("Loaded strategy has no evaluate() method")
        return evaluate(*args, **kwargs)

    def status(self, *, scope_key: str | None = None):
        return dynamic_strategy_runtime_manager.status(scope_key=scope_key)
