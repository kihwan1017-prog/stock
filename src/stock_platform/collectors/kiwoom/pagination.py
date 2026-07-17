from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ContinuationState:
    """키움 REST 연속조회 상태 (cont-yn / next-key)."""

    has_more: bool = False
    next_key: str | None = None

    @property
    def continue_yn(self) -> str | None:
        return "Y" if self.has_more else None

    @classmethod
    def from_response(
        cls,
        *,
        has_more: bool,
        next_key: str | None,
    ) -> ContinuationState:
        """응답 헤더 기반으로 다음 페이지 상태를 만든다."""

        cleaned_key = (next_key or "").strip() or None
        return cls(
            has_more=bool(has_more and cleaned_key),
            next_key=cleaned_key if has_more else None,
        )

    def as_request_headers(self) -> dict[str, Any]:
        headers: dict[str, Any] = {}
        if self.continue_yn:
            headers["cont-yn"] = self.continue_yn
        if self.next_key:
            headers["next-key"] = self.next_key
        return headers
