"""Controlled LIVE shutdown — 단계 실패가 전체를 중단하지 않는다.

관찰 GET에 의존하지 않는다. 각 mutation은 독립 시도.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from stock_platform.operation.observability_http import (
    CRITICAL_MUTATION_TIMEOUT,
    classify_http_result,
)


STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_UNKNOWN = "UNKNOWN"


@dataclass
class ShutdownStepResult:
    name: str
    status: str
    http: int | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "http": self.http,
            "detail": self.detail,
        }


def run_shutdown_steps(
    steps: list[tuple[str, Callable[[], tuple[int, Any]]]],
) -> list[ShutdownStepResult]:
    """한 단계 timeout/실패 후에도 다음 safety shutdown을 계속 실행한다."""

    results: list[ShutdownStepResult] = []
    for name, fn in steps:
        try:
            http, body = fn()
        except TimeoutError as exc:
            results.append(
                ShutdownStepResult(
                    name=name,
                    status=STATUS_UNKNOWN,
                    http=0,
                    detail=f"timeout:{type(exc).__name__}",
                )
            )
            continue
        except Exception as exc:  # noqa: BLE001
            results.append(
                ShutdownStepResult(
                    name=name,
                    status=STATUS_FAILED,
                    http=0,
                    detail=f"{type(exc).__name__}:{exc}"[:240],
                )
            )
            continue
        kind = classify_http_result(
            http_status=int(http or 0),
            body=body,
            kind="critical_mutation",
        )
        if kind == CRITICAL_MUTATION_TIMEOUT:
            results.append(
                ShutdownStepResult(
                    name=name,
                    status=STATUS_UNKNOWN,
                    http=int(http or 0),
                    detail="timeout",
                )
            )
            continue
        if 200 <= int(http or 0) < 300:
            results.append(
                ShutdownStepResult(
                    name=name, status=STATUS_SUCCESS, http=int(http), detail=None
                )
            )
            continue
        results.append(
            ShutdownStepResult(
                name=name,
                status=STATUS_FAILED,
                http=int(http or 0),
                detail=str(body)[:240],
            )
        )
    return results


def shutdown_sequence_names() -> tuple[str, ...]:
    return (
        "runner_stop",
        "runtime_stop",
        "exit_monitor_stop",
        "worker_stop",
        "arm_off",
        "live_off",
        "activation_disable",
    )
