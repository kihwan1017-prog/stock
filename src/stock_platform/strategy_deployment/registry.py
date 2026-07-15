from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class RealtimeStrategyProtocol(Protocol):
    def evaluate(self, *args, **kwargs):
        ...


StrategyFactory = Callable[
    [dict[str, Any]],
    RealtimeStrategyProtocol,
]


class StrategyFactoryRegistry:
    """
    strategy_code와 실제 실시간 전략 클래스 생성 함수를 연결한다.
    """

    def __init__(self) -> None:
        self._factories: dict[str, StrategyFactory] = {}

    def register(
        self,
        strategy_code: str,
        factory: StrategyFactory,
    ) -> None:
        normalized = strategy_code.strip().upper()

        if not normalized:
            raise ValueError(
                "strategy_code must not be empty"
            )

        if normalized in self._factories:
            raise ValueError(
                f"Strategy factory already registered: {normalized}"
            )

        self._factories[normalized] = factory

    def replace(
        self,
        strategy_code: str,
        factory: StrategyFactory,
    ) -> None:
        normalized = strategy_code.strip().upper()

        if not normalized:
            raise ValueError(
                "strategy_code must not be empty"
            )

        self._factories[normalized] = factory

    def create(
        self,
        *,
        strategy_code: str,
        parameter_payload: dict[str, Any],
    ) -> RealtimeStrategyProtocol:
        normalized = strategy_code.strip().upper()
        factory = self._factories.get(normalized)

        if factory is None:
            raise LookupError(
                f"Realtime strategy factory not registered: {normalized}"
            )

        return factory(parameter_payload)

    def contains(self, strategy_code: str) -> bool:
        return (
            strategy_code.strip().upper()
            in self._factories
        )

    def list_codes(self) -> list[str]:
        return sorted(self._factories)


strategy_factory_registry = StrategyFactoryRegistry()
