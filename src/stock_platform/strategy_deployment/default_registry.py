from __future__ import annotations

from typing import Any


class ParameterStrategyStub:
    """팩토리 미등록 전략용 스텁. Realtime Consumer는 MA Evaluator를 사용한다."""

    def __init__(self, parameter_payload: dict[str, Any] | None = None) -> None:
        self.parameter_payload = dict(parameter_payload or {})

    def evaluate(self, *args: Any, **kwargs: Any) -> None:
        return None


def configure_default_strategy_registry() -> None:
    """
    기본 전략 팩토리 등록.

    존재하지 않는 전략 클래스를 import하지 않는다.
    미등록 strategy_code는 ParameterStrategyStub으로 로드되어
    Scoped Runtime bootstrap이 LookupError로 전체 실패하지 않게 한다.
    """

    from stock_platform.strategy_deployment.registry import (
        strategy_factory_registry,
    )

    def _factory(params: dict[str, Any]) -> ParameterStrategyStub:
        return ParameterStrategyStub(params)

    # 문서/테스트에서 자주 쓰는 코드 + 기본 폴백
    for code in (
        "MA_CROSS_V1",
        "MOVING_AVERAGE_V1",
        "MOVING_AVERAGE",
        "DEFAULT",
        "PAPER_MA",
        "RSI_V1",
    ):
        strategy_factory_registry.replace(code, _factory)

    strategy_factory_registry.set_default_factory(_factory)
