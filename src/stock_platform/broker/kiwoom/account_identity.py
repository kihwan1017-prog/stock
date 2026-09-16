"""K_ONLY — Kiwoom 계좌 identity 정규화·비교.

Vault 8자리 vs broker 10자리(상품코드 접미) 등 broker 응답 형태 차이를
SHARED repository에 하드코딩하지 않기 위한 helper.
"""

from __future__ import annotations

from stock_platform.broker.snapshot_legacy_adoption import (
    SnapshotLegacyAdoptionProof,
)
from stock_platform.trading.account_masking import normalize_account_number


def kiwoom_account_digits(raw: str | None) -> str:
    """비교용 숫자만 추출."""

    normalized = normalize_account_number(raw or "")
    return "".join(ch for ch in normalized if ch.isdigit())


def matches_kiwoom_account_identity(left: str | None, right: str | None) -> bool:
    """동일 실계좌 여부.

    - 숫자열 완전 일치
    - 8자리 모계좌 + 2자리 상품코드(10자리) prefix 관계
    """

    a = kiwoom_account_digits(left)
    b = kiwoom_account_digits(right)
    if a and b:
        if a == b:
            return True
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        if len(shorter) == 8 and len(longer) == 10 and longer.startswith(shorter):
            return True
        return False
    # 숫자 없으면 normalize 문자열 비교 (방어)
    na = normalize_account_number(left or "")
    nb = normalize_account_number(right or "")
    return bool(na) and na == nb


def build_kiwoom_legacy_adoption_proof(
    *,
    target_uba_id: int,
    broker_account_number: str,
    vault_account_number: str | None = None,
) -> SnapshotLegacyAdoptionProof:
    """Vault·broker 계좌를 ownership-proven matcher로 묶는다."""

    refs = [broker_account_number]
    if vault_account_number:
        refs.append(vault_account_number)

    def _matcher(candidate: str) -> bool:
        return any(
            matches_kiwoom_account_identity(candidate, ref)
            for ref in refs
            if ref
        )

    return SnapshotLegacyAdoptionProof(
        target_uba_id=int(target_uba_id),
        broker_code="KIWOOM",
        account_matcher=_matcher,
    )
