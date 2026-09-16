"""Risk/주문 계층 — PaperAccount XOR UserBrokerAccount 소유권."""

from __future__ import annotations

LIVE_ENVIRONMENTS = frozenset({"LIVE", "LIVE_SHADOW"})
PAPER_ENVIRONMENTS = frozenset({"PAPER", "PAPER_TRADING"})
MOCK_ENVIRONMENTS = frozenset({"MOCK"})


def validate_account_ownership(
    *,
    account_id: int | None,
    user_broker_account_id: int | None,
    environment: str,
) -> tuple[int | None, int | None]:
    """환경별 Paper/UBA XOR 검증.

    Returns:
        (paper_account_id, user_broker_account_id)

    Raises:
        ValueError: 소유권 규칙 위반 (코드 문자열).
    """

    env = str(environment or "").strip().upper()
    paper: int | None
    uba: int | None

    if account_id is None:
        paper = None
    else:
        paper = int(account_id)
        if paper <= 0:
            raise ValueError("PAPER_ACCOUNT_REQUIRED")

    if user_broker_account_id is None:
        uba = None
    else:
        uba = int(user_broker_account_id)
        if uba <= 0:
            raise ValueError("UBA_REQUIRED")

    if paper is not None and uba is not None:
        raise ValueError("ACCOUNT_OWNERSHIP_BOTH")

    if env in LIVE_ENVIRONMENTS:
        if uba is None:
            raise ValueError("UBA_REQUIRED")
        # LIVE는 paper slot 금지
        return None, uba

    if env in PAPER_ENVIRONMENTS:
        if paper is None:
            raise ValueError("PAPER_ACCOUNT_REQUIRED")
        return paper, None

    if env in MOCK_ENVIRONMENTS:
        # MOCK은 명시적 XOR — Paper/LIVE 암묵 혼용 금지
        if paper is None and uba is None:
            raise ValueError("ACCOUNT_CONTEXT_MISSING")
        return paper, uba

    if paper is None and uba is None:
        raise ValueError("ACCOUNT_CONTEXT_MISSING")
    return paper, uba
