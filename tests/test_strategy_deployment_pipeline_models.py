from stock_platform.strategy_deployment.pipeline_models import (
    StrategyDeploymentPipelineStatus,
)


def test_pipeline_status_values():
    assert (
        StrategyDeploymentPipelineStatus.SWITCHED.value
        == "SWITCHED"
    )
    assert (
        StrategyDeploymentPipelineStatus.ROLLED_BACK.value
        == "ROLLED_BACK"
    )
