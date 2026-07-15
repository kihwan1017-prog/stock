from stock_platform.strategy_deployment.pipeline_runtime import (
    StrategyDeploymentPipelineManager,
)


def test_pipeline_manager_initial_status():
    manager = StrategyDeploymentPipelineManager()

    status = manager.status()

    assert status["running"] is False
    assert status["last_result"] is None
    assert status["last_error"] is None
