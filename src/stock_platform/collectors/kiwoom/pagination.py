from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContinuationState:
    """키움 REST 연속조회 상태."""

    has_more: bool = False
    next_key: str | None = None

    @property
    def continue_yn(self) -> str | None:
        return "Y" if self.has_more else None
