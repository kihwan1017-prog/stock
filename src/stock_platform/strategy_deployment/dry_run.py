from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stock_platform.strategy_deployment.runtime_models import LoadedStrategyRuntime
from stock_platform.strategy_deployment.switch_models import StrategyDryRunResult


class StrategyDryRunService:
    """
    실전 교체 전 최소 검증:
    - evaluate 메서드 존재
    - 파라미터가 dict
    - 선택적 validate_configuration 실행
    - 선택적 warmup 실행
    """

    def run(
        self,
        *,
        runtime: LoadedStrategyRuntime,
        strategy: object,
        sample_context: dict[str, Any] | None = None,
    ) -> StrategyDryRunResult:
        checks: list[dict[str, Any]] = []

        evaluate = getattr(strategy, "evaluate", None)
        checks.append(
            {
                "check": "evaluate_method",
                "passed": callable(evaluate),
                "message": (
                    "evaluate() available"
                    if callable(evaluate)
                    else "evaluate() missing"
                ),
            }
        )

        checks.append(
            {
                "check": "parameter_payload",
                "passed": isinstance(
                    runtime.parameter_payload,
                    dict,
                ),
                "message": "parameter_payload is dict",
            }
        )

        validator = getattr(
            strategy,
            "validate_configuration",
            None,
        )

        if callable(validator):
            try:
                validator()
                checks.append(
                    {
                        "check": "validate_configuration",
                        "passed": True,
                        "message": "configuration valid",
                    }
                )
            except Exception as exc:
                checks.append(
                    {
                        "check": "validate_configuration",
                        "passed": False,
                        "message": str(exc),
                    }
                )

        warmup = getattr(strategy, "warmup", None)

        if callable(warmup):
            try:
                warmup(sample_context or {})
                checks.append(
                    {
                        "check": "warmup",
                        "passed": True,
                        "message": "warmup completed",
                    }
                )
            except Exception as exc:
                checks.append(
                    {
                        "check": "warmup",
                        "passed": False,
                        "message": str(exc),
                    }
                )

        passed = all(
            item["passed"]
            for item in checks
        )

        return StrategyDryRunResult(
            passed=passed,
            strategy_code=runtime.strategy_code,
            deployment_id=runtime.deployment_id,
            checks=checks,
            generated_at=datetime.now(timezone.utc),
        )
