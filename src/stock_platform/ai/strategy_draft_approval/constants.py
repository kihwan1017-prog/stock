"""STEP 12-3 — Strategy Draft Approval 상태/전이 상수.

Draft 자체의 생성 상태(DRAFT/REGENERATED/SUPERSEDED/ARCHIVED, STEP12-2-1)와
"최종 승인 결정"은 별도 도메인이다. 하나의 Draft 행은 그 생성 상태와
무관하게, 그 Draft를 대상으로 한 승인 결정(Approval)을 최대 1개까지
"활성"(APPROVED) 상태로 가질 수 있다.

상태:
- PENDING: 승인 결정 대기(현재 구현은 approve()/reject() 호출 시점에
  PENDING -> APPROVED/REJECTED로 즉시 전이하며, 별도 "심사 요청" 클릭
  단계를 두지 않는다 — Draft가 DRAFT 상태인 것 자체가 이미 "승인 대기"를
  의미하므로 submit_for_approval()은 생략한다).
- APPROVED: 최종 승인 — Strategy Definition이 정확히 1개 생성된다.
- REJECTED: 반려 — Draft 본문은 보존되며 삭제되지 않는다.
- REVOKED: 승인 취소 — 이미 생성된 Strategy Definition은 비활성화(is_active
  =False)될 뿐 hard delete하지 않는다.
- SUPERSEDED: 동일 Strategy Request에 대해 다른(더 새로운) Draft가 새로
  승인되면서 자동으로 대체됨(REJECTED/REVOKED로 종결된 결정을 뒤집는 것과
  달리, 이는 "새 근거 채택"에 의한 자연스러운 대체이므로 별도 상태로 구분).

금지된 전이:
- REJECTED -> APPROVED
- REVOKED -> APPROVED
- APPROVED 결정 자체를 수정(덮어쓰기) — 새 Approval 행을 만들 뿐 기존 행은
  상태만 바뀐다.
- 동일 Draft에 대해 활성(APPROVED) Approval 2개 이상 동시 존재.
"""

from __future__ import annotations

APPROVAL_STATUS = frozenset(
    {
        "PENDING",
        "APPROVED",
        "REJECTED",
        "REVOKED",
        "SUPERSEDED",
    }
)

TERMINAL_APPROVAL_STATUSES = frozenset({"REJECTED", "REVOKED", "SUPERSEDED"})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"APPROVED", "REJECTED"}),
    "APPROVED": frozenset({"REVOKED", "SUPERSEDED"}),
    "REJECTED": frozenset(),
    "REVOKED": frozenset(),
    "SUPERSEDED": frozenset(),
}

REASON_MAX_LENGTH = 1000
MIN_REASON_LENGTH = 1

STRATEGY_DRAFT_APPROVAL_PERMISSIONS = (
    "STRATEGY_DRAFT_APPROVE",
    "STRATEGY_DRAFT_REJECT",
    "STRATEGY_DRAFT_APPROVAL_REVOKE",
    "STRATEGY_DRAFT_APPROVAL_VIEW",
)

DEFINITION_SCHEMA_VERSION = "1.0"
