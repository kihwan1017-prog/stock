"""STEP 12-2-1 — Strategy Draft 상태/버전/리비전 정책.

Version/Revision 정책
---------------------
동일 Strategy Request에 대해:

- 최초 Draft 생성 -> version=1, revision=1, status=DRAFT
- 같은 version 안에서 "Revision 생성"(create_revision) -> revision += 1,
  version은 그대로. 이전 revision 행은 DRAFT -> REGENERATED로 전이한다
  (같은 version 내에서 새 revision에 의해 대체됨을 의미).
- 동일 Strategy Request에 "새 Draft 생성"(create)을 다시 호출하면
  새 version(= 기존 최대 version + 1), revision=1로 생성되고, 그 직전
  version의 최신(활성) 행은 DRAFT -> SUPERSEDED로 전이한다(새 version에
  의해 대체됨을 의미 — REGENERATED와 구분되는 상위 개념).

예시(Strategy Request #15):
    create           -> v1        (DRAFT)
    create_revision  -> v1        (REGENERATED) / v1-r2 (DRAFT)
    create_revision  -> v1-r2     (REGENERATED) / v1-r3 (DRAFT)
    create (새 버전)  -> v1-r3     (SUPERSEDED)  / v2    (DRAFT)
    create_revision  -> v2        (REGENERATED) / v2-r2 (DRAFT)

즉:
- REGENERATED = 같은 version 내에서 새 revision에 의해 대체됨
- SUPERSEDED  = 새 version에 의해 대체됨(해당 version의 마지막 revision에만 적용)
- ARCHIVED    = 관리자가 명시적으로 보관 처리(어느 상태에서든 도달 가능한 종결 상태)
- DRAFT       = 현재 활성(조회/수정/Revision 생성/버전 생성/Archive 가능) 상태.
  Strategy Request당 동시에 최대 1개의 DRAFT 행만 존재한다(부분 유니크 인덱스로 강제).
"""

from __future__ import annotations

STRATEGY_DRAFT_STATUS = frozenset(
    {
        "DRAFT",
        "REGENERATED",
        "ARCHIVED",
        "SUPERSEDED",
    }
)

# DRAFT만 활성(편집/리비전 생성/버전 생성/Archive 가능) 상태다.
ACTIVE_STRATEGY_DRAFT_STATUS = "DRAFT"

# ARCHIVED는 완전 종결 상태 — 어떤 후속 전이도 없다.
TERMINAL_STRATEGY_DRAFT_STATUSES = frozenset({"ARCHIVED"})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"REGENERATED", "SUPERSEDED", "ARCHIVED"}),
    "REGENERATED": frozenset({"ARCHIVED"}),
    "SUPERSEDED": frozenset({"ARCHIVED"}),
    "ARCHIVED": frozenset(),
}

# Strategy Request는 APPROVED 상태여야만 Draft 생성 대상이 될 수 있다
# (STEP12-1/12-1A의 승인 게이트를 그대로 신뢰 — 재검증하지 않고 상태만 확인).
ELIGIBLE_STRATEGY_REQUEST_STATUS = "APPROVED"

STRATEGY_DRAFT_PERMISSIONS = (
    "STRATEGY_DRAFT_VIEW",
    "STRATEGY_DRAFT_CREATE",
    "STRATEGY_DRAFT_UPDATE",
    "STRATEGY_DRAFT_ARCHIVE",
)

TITLE_MAX_LENGTH = 200
SUMMARY_MAX_LENGTH = 2000
REASON_MAX_LENGTH = 1000

# Draft 생성/수정 시 편집 가능한 컨텐츠 필드(내부 헬퍼에서 공통 사용).
CONTENT_FIELDS = (
    "title",
    "summary",
    "entry_rule",
    "exit_rule",
    "stop_loss_rule",
    "take_profit_rule",
    "position_sizing_rule",
    "timeframe",
    "market_type",
    "risk_parameters",
    "indicator_configuration",
    "llm_provider",
    "llm_model",
    "prompt_version",
)
