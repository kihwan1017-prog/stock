"""SHARED — Legacy RETIRED unbound snapshot adoption proof (caller-owned).

Repository는 broker별 계좌 문자열 규칙을 하드코딩하지 않는다.
호출측(Kiwoom helper 등)이 ownership-proven matcher를 제공한다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SnapshotLegacyAdoptionProof:
    """RETIRED + UBA NULL row adopt 허용 증명.

    account_matcher: candidate.account_number → 동일 실계좌 여부.
    """

    target_uba_id: int
    broker_code: str
    account_matcher: Callable[[str], bool]

    def matches_account(self, account_number: str) -> bool:
        try:
            return bool(self.account_matcher(str(account_number or "")))
        except Exception:  # noqa: BLE001 — matcher 실패는 미일치로 취급
            return False


class LegacySnapshotAdoptionRejected(ValueError):
    """ownership 모호·충돌 시 fail-closed."""

    code = "LEGACY_SNAPSHOT_ADOPTION_REJECTED"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
