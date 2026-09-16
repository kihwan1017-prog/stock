"""STEP 8-5-18 — 내부 계좌 식별 원칙 (UBA / Paper Account).

LIVE 내부 식별자: user_broker_account_id
Paper 내부 식별자: paper_account_id

account_number 는 Broker API·마스킹 표시에만 허용한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AccountIdentityErrorCode(StrEnum):
    UBA_REQUIRED = "UBA_REQUIRED"
    PAPER_ACCOUNT_REQUIRED = "PAPER_ACCOUNT_REQUIRED"
    LEGACY_ACCOUNT_NUMBER_ONLY = "LEGACY_ACCOUNT_NUMBER_ONLY"
    ACCOUNT_CONTEXT_MISSING = "ACCOUNT_CONTEXT_MISSING"
    SYSTEM_SHARED_ACCOUNT_BLOCKED = "SYSTEM_SHARED_ACCOUNT_BLOCKED"
    ACCOUNT_RESOURCE_MISMATCH = "ACCOUNT_RESOURCE_MISMATCH"


class AccountIdentityError(ValueError):
    """계좌 식별 Fail Closed."""

    def __init__(self, code: AccountIdentityErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


# 회원 계좌 Sync/Settlement/Risk Job 에서 금지
MEMBER_ACCOUNT_JOB_TYPES = frozenset(
    {
        "ACCOUNT_SNAPSHOT",
        "ACCOUNT_BALANCE",
        "ACCOUNT_POSITION",
        "BROKER_SNAPSHOT",
        "KRX_EQUITY_SNAPSHOT",
        "UPBIT_ACCOUNT_SYNC",
        "KIWOOM_ACCOUNT_SYNC",
        "SETTLEMENT",
        "EOD_SETTLEMENT",
        "DAILY_LOSS",
        "RISK_EVALUATION",
        "RECONCILIATION",
    }
)

# SYSTEM_SHARED 로 허용되는 시장 공통 Job
SYSTEM_SHARED_ALLOWED_JOB_TYPES = frozenset(
    {
        "MARKET_INSTRUMENT",
        "MARKET_QUOTE",
        "MARKET_TRADE",
        "MARKET_CANDLE",
        "EXCHANGE_STATUS",
        "MARKET_SESSION",
        "DISCLOSURE",
        "NEWS",
    }
)


@dataclass(frozen=True, slots=True)
class LiveAccountContext:
    user_id: int
    user_broker_account_id: int
    broker_code: str
    market: str
    currency: str


@dataclass(frozen=True, slots=True)
class PaperAccountContext:
    user_id: int
    paper_account_id: int
    market: str
    currency: str


def require_live_account_context(
    *,
    user_id: int | None,
    user_broker_account_id: int | None,
    broker_code: str | None,
    market: str | None = None,
    currency: str | None = None,
    account_number: str | None = None,
) -> LiveAccountContext:
    """LIVE 내부 경로 — UBA 필수. account_number만 있으면 거부."""

    if user_broker_account_id is None:
        if account_number and str(account_number).strip():
            raise AccountIdentityError(
                AccountIdentityErrorCode.LEGACY_ACCOUNT_NUMBER_ONLY,
                "LIVE path rejects account_number-only identity",
            )
        raise AccountIdentityError(
            AccountIdentityErrorCode.UBA_REQUIRED,
            "user_broker_account_id is required for LIVE account identity",
        )
    if user_id is None:
        raise AccountIdentityError(
            AccountIdentityErrorCode.ACCOUNT_CONTEXT_MISSING,
            "user_id is required for LIVE account identity",
        )
    broker = (broker_code or "").strip().upper()
    if not broker:
        raise AccountIdentityError(
            AccountIdentityErrorCode.ACCOUNT_CONTEXT_MISSING,
            "broker_code is required for LIVE account identity",
        )
    return LiveAccountContext(
        user_id=int(user_id),
        user_broker_account_id=int(user_broker_account_id),
        broker_code=broker,
        market=(market or "KRX").strip().upper(),
        currency=(currency or "KRW").strip().upper(),
    )


def require_paper_account_context(
    *,
    user_id: int | None,
    paper_account_id: int | None,
    market: str | None = None,
    currency: str | None = None,
    account_number: str | None = None,
) -> PaperAccountContext:
    """Paper 내부 경로 — paper_account_id 필수."""

    if paper_account_id is None:
        if account_number and str(account_number).strip():
            raise AccountIdentityError(
                AccountIdentityErrorCode.LEGACY_ACCOUNT_NUMBER_ONLY,
                "Paper path rejects account_number-only identity",
            )
        raise AccountIdentityError(
            AccountIdentityErrorCode.PAPER_ACCOUNT_REQUIRED,
            "paper_account_id is required for Paper account identity",
        )
    if user_id is None:
        raise AccountIdentityError(
            AccountIdentityErrorCode.ACCOUNT_CONTEXT_MISSING,
            "user_id is required for Paper account identity",
        )
    return PaperAccountContext(
        user_id=int(user_id),
        paper_account_id=int(paper_account_id),
        market=(market or "KRX").strip().upper(),
        currency=(currency or "KRW").strip().upper(),
    )


def validate_scheduler_account_payload(
    payload: dict,
    *,
    job_type: str,
) -> None:
    """계좌 관련 Scheduler Payload 표준 검증 (Fail Closed)."""

    jt = (job_type or "").strip().upper()
    requested_by = str(payload.get("requested_by") or "").strip().upper()
    is_system_shared = requested_by in {
        "SYSTEM_SHARED",
        "SYSTEM",
        "MAIN",
        "DEFAULT",
        "DEFAULT_ACCOUNT",
    } or bool(payload.get("system_shared"))

    if is_system_shared and jt in MEMBER_ACCOUNT_JOB_TYPES:
        raise AccountIdentityError(
            AccountIdentityErrorCode.SYSTEM_SHARED_ACCOUNT_BLOCKED,
            f"SYSTEM_SHARED cannot run member account job: {jt}",
        )

    if jt not in MEMBER_ACCOUNT_JOB_TYPES:
        return

    uba = payload.get("user_broker_account_id")
    paper = payload.get("paper_account_id")
    account_number = payload.get("account_number")
    broker_only = (
        payload.get("broker_code")
        and uba is None
        and paper is None
        and not payload.get("user_id")
    )

    if uba is None and paper is None:
        if account_number or broker_only:
            raise AccountIdentityError(
                AccountIdentityErrorCode.LEGACY_ACCOUNT_NUMBER_ONLY,
                "Scheduler member job requires user_broker_account_id "
                "or paper_account_id",
            )
        raise AccountIdentityError(
            AccountIdentityErrorCode.UBA_REQUIRED,
            "Scheduler member job requires account identity",
        )

    if not payload.get("job_type") and not jt:
        raise AccountIdentityError(
            AccountIdentityErrorCode.ACCOUNT_CONTEXT_MISSING,
            "job_type is required",
        )
    if not payload.get("correlation_id"):
        raise AccountIdentityError(
            AccountIdentityErrorCode.ACCOUNT_CONTEXT_MISSING,
            "correlation_id is required for account jobs",
        )
    if not payload.get("requested_by"):
        raise AccountIdentityError(
            AccountIdentityErrorCode.ACCOUNT_CONTEXT_MISSING,
            "requested_by is required for account jobs",
        )

    if uba is not None and not payload.get("broker_code"):
        raise AccountIdentityError(
            AccountIdentityErrorCode.ACCOUNT_CONTEXT_MISSING,
            "broker_code is required for LIVE account jobs",
        )


def uba_kill_switch_scope(user_broker_account_id: int) -> str:
    return f"UBA:{int(user_broker_account_id)}"


def paper_kill_switch_scope(paper_account_id: int) -> str:
    return f"PAPER:{int(paper_account_id)}"
