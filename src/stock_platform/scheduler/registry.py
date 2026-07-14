from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


JobHandler = Callable[
    [dict[str, Any]],
    dict[str, Any] | Awaitable[dict[str, Any]],
]


@dataclass(frozen=True, slots=True)
class RegisteredJob:
    name: str
    group: str
    description: str
    handler: JobHandler


class JobRegistry:
    """실행 가능한 내부 작업을 이름으로 관리한다."""

    def __init__(self) -> None:
        self._jobs: dict[str, RegisteredJob] = {}

    def register(
        self,
        *,
        name: str,
        group: str,
        description: str,
        handler: JobHandler,
    ) -> None:
        normalized = name.strip()

        if not normalized:
            raise ValueError("job name is required")

        if normalized in self._jobs:
            raise ValueError(
                f"Job already registered: {normalized}"
            )

        self._jobs[normalized] = RegisteredJob(
            name=normalized,
            group=group.strip().upper() or "DEFAULT",
            description=description.strip(),
            handler=handler,
        )

    def get(self, name: str) -> RegisteredJob:
        try:
            return self._jobs[name]
        except KeyError as exc:
            raise LookupError(
                f"Job not found: {name}"
            ) from exc

    def list_jobs(self) -> list[RegisteredJob]:
        return sorted(
            self._jobs.values(),
            key=lambda item: (
                item.group,
                item.name,
            ),
        )
