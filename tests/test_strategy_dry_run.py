from datetime import datetime, timezone

from stock_platform.strategy_deployment.dry_run import (
    StrategyDryRunService,
)
from stock_platform.strategy_deployment.runtime_models import (
    LoadedStrategyRuntime,
)


class ValidStrategy:
    def evaluate(self):
        return None

    def validate_configuration(self):
        return None

    def warmup(self, context):
        return None


class InvalidStrategy:
    pass


def _runtime():
    return LoadedStrategyRuntime(
        deployment_id=1,
        strategy_code="TEST_V1",
        market_code="KRX",
        symbol="005930",
        parameter_payload={},
        loaded_at=datetime.now(timezone.utc),
    )


def test_dry_run_passes_valid_strategy():
    result = StrategyDryRunService().run(
        runtime=_runtime(),
        strategy=ValidStrategy(),
        sample_context={},
    )

    assert result.passed is True


def test_dry_run_fails_without_evaluate():
    result = StrategyDryRunService().run(
        runtime=_runtime(),
        strategy=InvalidStrategy(),
        sample_context={},
    )

    assert result.passed is False
