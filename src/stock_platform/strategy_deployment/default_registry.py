from __future__ import annotations

from stock_platform.strategy_deployment.registry import (
    strategy_factory_registry,
)


def configure_default_strategy_registry() -> None:
    """
    실제 프로젝트 전략 클래스에 맞게 factory를 등록한다.

    아래 예시는 구조만 제공합니다. 존재하지 않는 클래스를
    자동 import하지 않아 서버 시작 오류를 방지합니다.
    """

    # 예:
    #
    # from stock_platform.strategy.ma_cross import MaCrossStrategy
    #
    # strategy_factory_registry.replace(
    #     "MA_CROSS_V1",
    #     lambda params: MaCrossStrategy(
    #         short_window=int(params["short_window"]),
    #         long_window=int(params["long_window"]),
    #     ),
    # )
    #
    # from stock_platform.strategy.rsi import RsiStrategy
    #
    # strategy_factory_registry.replace(
    #     "RSI_V1",
    #     lambda params: RsiStrategy(
    #         period=int(params.get("period", 14)),
    #         oversold=float(params.get("oversold", 30)),
    #         overbought=float(params.get("overbought", 70)),
    #     ),
    # )

    return None
