from stock_platform.strategy_deployment.registry import (
    StrategyFactoryRegistry,
)


class FakeStrategy:
    def __init__(self, value):
        self.value = value

    def evaluate(self):
        return self.value


def test_registers_and_creates_strategy() -> None:
    registry = StrategyFactoryRegistry()

    registry.register(
        "TEST_V1",
        lambda params: FakeStrategy(
            params["value"]
        ),
    )

    strategy = registry.create(
        strategy_code="test_v1",
        parameter_payload={"value": 10},
    )

    assert strategy.evaluate() == 10
    assert registry.contains("TEST_V1") is True


def test_unknown_strategy_is_rejected() -> None:
    registry = StrategyFactoryRegistry()

    try:
        registry.create(
            strategy_code="UNKNOWN",
            parameter_payload={},
        )
    except LookupError as exc:
        assert "not registered" in str(exc)
    else:
        raise AssertionError(
            "LookupError was not raised"
        )
