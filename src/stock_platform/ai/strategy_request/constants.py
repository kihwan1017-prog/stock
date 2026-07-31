"""STEP 12-1 — Strategy Request 상태/전이 상수."""

from __future__ import annotations

STRATEGY_REQUEST_STATUS = frozenset(
    {
        "PENDING_REVIEW",
        "APPROVED",
        "REJECTED",
        "CANCELLED",
        "EXPIRED",
    }
)

TERMINAL_STRATEGY_REQUEST_STATUSES = frozenset(
    {"APPROVED", "REJECTED", "CANCELLED", "EXPIRED"}
)

# 상태 전이표. EXPIRED는 상태 모델에 정의만 하고 이번 STEP에서는 어떤
# 코드 경로도 자동으로 전이시키지 않는다(Scheduler WRITE 금지 범위).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING_REVIEW": frozenset({"APPROVED", "REJECTED", "CANCELLED", "EXPIRED"}),
    "APPROVED": frozenset(),
    "REJECTED": frozenset(),
    "CANCELLED": frozenset(),
    "EXPIRED": frozenset(),
}

# candidate_lifecycle.lifecycle_status 중 Strategy Request 생성이 허용되는
# "ACTIVE" 집합. ai.candidate_lifecycle.constants.LIFECYCLE_STATUS에는 리터럴
# "ACTIVE" 상태가 없어, PROMOTED/ACTIVE_REVIEW(정상 운영 중 상태)만을
# "ACTIVE"로 간주한다. REVOKED/EXPIRED/SUPERSEDED는 물론, 재검증·철회
# 절차가 진행 중인 상태(STALE/REVALIDATION_*/REVOCATION_*)와 CANCELLED/
# ARCHIVED도 모두 배제한다 — 신뢰성이 확정되지 않은 후보를 사람이 심사
# 요청하는 것을 막기 위함이다.
ELIGIBLE_CANDIDATE_LIFECYCLE_STATUSES = frozenset({"PROMOTED", "ACTIVE_REVIEW"})

STRATEGY_REQUEST_PERMISSIONS = (
    "STRATEGY_REQUEST_VIEW",
    "STRATEGY_REQUEST_CREATE",
    "STRATEGY_REQUEST_CANCEL",
    "STRATEGY_REQUEST_APPROVE",
    "STRATEGY_REQUEST_REJECT",
)

REQUEST_REASON_MAX_LENGTH = 1000
REVIEW_NOTE_MAX_LENGTH = 1000
