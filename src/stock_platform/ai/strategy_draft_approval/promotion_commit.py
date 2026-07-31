"""STEP 12-16/16R — Promotion Commit + Strategy Promotion State/History.

STEP12-15에서 생성된 Decision Package/Human Decision(APPROVE_FOR_PROMOTION)
을 최종 재검증한 뒤, 관리자의 명시적 요청으로만 Promotion Commit(불변
기록)을 생성한다. Human Decision이 존재한다고 자동 실행하지 않는다 —
Promotion Commit은 별도의, 명시적인 관리자 작업이다. Activation/
Deployment/Runtime 등록/Scheduler/Broker/Order/Paper·Live Trading은
전혀 수행하지 않는다(다음 STEP의 별도 검토 대상).

STEP12-16R 재작업 사유: 기존 STEP12-16은 Promotion Commit 행에
`committed_lifecycle_status="PROMOTED"`를 "기록"만 했을 뿐, 실제로
전이시키는 공식 상태 축이 없었다(사실상 Promotion Event Snapshot
저장까지만 수행 — FAIL 판정). 이제 `strategy_promotion_state`(현재
상태 1개, Strategy Definition당 UNIQUE)와 `strategy_promotion_history`
(불변 전이 기록)를 Promotion Commit과 **같은 Transaction**에서
전이·기록한다. 기존 `strategy_promotion_commit` 테이블/컬럼은 그대로
유지한다(삭제·rename 없음) — 다만 그 컬럼명(`committed_lifecycle_status`)
이 실제로는 Candidate Lifecycle이 아니라는 점을 API 응답에서
`current_promotion_status` 등 의미가 분명한 필드로 명확히 구분해
노출한다.

핵심 설계 결정 — Candidate Lifecycle에 절대 WRITE하지 않음(§
promotion_state_entities.py 모듈 docstring 참고): `ai.candidate_lifecycle
.lifecycle_status`의 `PROMOTED`는 STEP11 "AI Candidate Promotion
Gateway"(Candidate가 Strategy Request 생성 자격을 얻는 훨씬 이른
단계)의 의미이고, 이 STEP의 "Strategy Definition Promotion"은 그보다
훨씬 뒤 단계의 완전히 다른 상태 축이다. 같은 필드에 같은 값을 다시
쓰면 두 서로 다른 Lifecycle 개념이 충돌하므로, candidate_lifecycle은
읽기 전용 게이팅에만 사용한다(REVOKED/EXPIRED 등이면 차단). Strategy
Promotion State가 이 STEP의 공식 Source of Truth이며 Candidate
Lifecycle과 완전히 독립적으로 전이한다.

재사용(중복 생성 금지 확인):
- Decision Package/Human Decision 조회·검증은 STEP12-15
  `check_package_staleness()`를 그대로 재사용(재계산 없음).
- Approval 상태 게이팅은 STEP12-5/10/15가 이미 확립한 `StrategyDraftApprovalEntity
  .status` 체크와 동일한 규칙을 재사용.
- Row Lock은 기존 `strategy_draft_approval/service.py`의 `with_for_update()`
  패턴을 그대로 재사용(새 Lock 메커니즘 없음).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_lifecycle.entities import AICandidateLifecycleEntity
from stock_platform.ai.strategy_draft_approval.backtest_spec import _canonical_json, _hash
from stock_platform.ai.strategy_draft_approval.decision_package import (
    _STALE_LIFECYCLE_STATUSES,
    check_package_staleness,
)
from stock_platform.ai.strategy_draft_approval.decision_package_entities import (
    StrategyDecisionPackageEntity,
    StrategyHumanDecisionEntity,
)
from stock_platform.ai.strategy_draft_approval.entities import StrategyDraftApprovalEntity
from stock_platform.ai.strategy_draft_approval.promotion_commit_entities import (
    StrategyPromotionCommitEntity,
)
from stock_platform.ai.strategy_draft_approval.promotion_state_entities import (
    PROMOTION_STATE_NOT_PROMOTED,
    PROMOTION_STATE_PROMOTION_COMMITTED,
    StrategyPromotionHistoryEntity,
    StrategyPromotionStateEntity,
)
from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

ALGORITHM_VERSION = "1.0.0"
COMMITTED_LIFECYCLE_STATUS = "PROMOTED"
CONFIRMATION_TEXT_REQUIRED = "PROMOTE"

# Promotion Commit 결과 필드의 고정 의미(§ STEP12-16 명세) — Activation/
# Deployment/Runtime은 이 STEP에서 절대 시작되지 않는다.
FIXED_ACTIVATION_STATUS = "NOT_STARTED"
FIXED_DEPLOYMENT_STATUS = "NOT_STARTED"
FIXED_RUNTIME_STATUS = "NOT_REGISTERED"
FIXED_NEXT_ACTION = "REVIEW_ACTIVATION"

# § STEP12-16R — Strategy Promotion State 전이 허용표. 이번 STEP에서
# 실제로 쓰이는 전이는 NOT_PROMOTED -> PROMOTION_COMMITTED 하나뿐이다.
# ACTIVATION_REVIEW 이후 상태는 Enum 값만 마련해 두고(§ promotion_state
# _entities.py) 이번 STEP에서는 그 어떤 상태에서도 전이를 허용하지
# 않는다(향후 STEP 전용).
_ALLOWED_PROMOTION_STATE_TRANSITIONS: dict[str, frozenset[str]] = {
    PROMOTION_STATE_NOT_PROMOTED: frozenset({PROMOTION_STATE_PROMOTION_COMMITTED}),
}


def _can_transition_promotion_state(from_status: str, to_status: str) -> bool:
    return to_status in _ALLOWED_PROMOTION_STATE_TRANSITIONS.get(from_status, frozenset())


class PromotionCommitError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _normalize_confirmation_text(value: str) -> str:
    """확인값 정책(결정적) — 앞뒤 공백 제거 후 대문자로 비교한다("promote"/
    "  PROMOTE  " 모두 허용, 그 외 문자열은 전부 차단)."""
    return (value or "").strip().upper()


def compute_promotion_commit_hash(
    *,
    strategy_definition_id: int,
    strategy_definition_version: int | None,
    definition_hash: str | None,
    executable_hash: str | None,
    approval_snapshot_hash: str | None,
    decision_package_id: int,
    package_input_hash: str,
    human_decision_id: int,
    decision_input_hash: str,
    promotion_readiness_hash: str,
    previous_lifecycle_status: str | None,
    committed_lifecycle_status: str,
    committed_by: str,
    committed_at: datetime,
    confirmation_hash: str,
    algorithm_version: str,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id,
        "strategy_definition_version": strategy_definition_version,
        "definition_hash": definition_hash,
        "executable_hash": executable_hash,
        "approval_snapshot_hash": approval_snapshot_hash,
        "decision_package_id": decision_package_id,
        "package_input_hash": package_input_hash,
        "human_decision_id": human_decision_id,
        "decision_input_hash": decision_input_hash,
        "promotion_readiness_hash": promotion_readiness_hash,
        "previous_lifecycle_status": previous_lifecycle_status,
        "committed_lifecycle_status": committed_lifecycle_status,
        "committed_by": committed_by,
        "committed_at": committed_at.isoformat(),
        "confirmation_hash": confirmation_hash,
        "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def compute_promotion_state_hash(
    *,
    strategy_definition_id: int,
    current_status: str,
    status_version: int,
    current_promotion_commit_id: int | None,
    previous_event_hash: str | None,
    transitioned_at: datetime,
    algorithm_version: str,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id,
        "current_status": current_status,
        "status_version": status_version,
        "current_promotion_commit_id": current_promotion_commit_id,
        "previous_event_hash": previous_event_hash,
        "transitioned_at": transitioned_at.isoformat(),
        "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def compute_promotion_state_event_hash(
    *,
    strategy_definition_id: int,
    promotion_commit_id: int,
    previous_status: str,
    new_status: str,
    human_decision_id: int,
    decision_package_id: int,
    actor: str,
    occurred_at: datetime,
    transition_reason: str,
    algorithm_version: str,
) -> str:
    canonical = {
        "strategy_definition_id": strategy_definition_id,
        "promotion_commit_id": promotion_commit_id,
        "previous_status": previous_status,
        "new_status": new_status,
        "human_decision_id": human_decision_id,
        "decision_package_id": decision_package_id,
        "actor": actor,
        "occurred_at": occurred_at.isoformat(),
        "transition_reason": transition_reason,
        "algorithm_version": algorithm_version,
    }
    return _hash(_canonical_json(canonical))


def _ensure_and_lock_promotion_state(
    session: Session, strategy_definition_id: int, *, actor: str
) -> StrategyPromotionStateEntity:
    """§ STEP12-16R — "행이 아직 없으면 만들고, 있으면 잠근다"를 동시성
    안전하게 수행한다. `INSERT ... ON CONFLICT DO NOTHING`으로 행 존재를
    먼저 보장한 뒤(두 Transaction이 동시에 최초 생성을 시도해도 하나만
    성공) `SELECT ... FOR UPDATE`로 잠근다 — 두 번째 Transaction은 첫
    Transaction이 commit할 때까지 여기서 대기하므로, 이 함수 리턴 이후의
    모든 검증은 항상 최신 상태를 보고 직렬화된다."""
    initial_hash = compute_promotion_state_hash(
        strategy_definition_id=strategy_definition_id,
        current_status=PROMOTION_STATE_NOT_PROMOTED,
        status_version=0,
        current_promotion_commit_id=None,
        previous_event_hash=None,
        transitioned_at=datetime.now(timezone.utc),
        algorithm_version=ALGORITHM_VERSION,
    )
    session.execute(
        text(
            """
            INSERT INTO trading.strategy_promotion_state
            (strategy_definition_id, current_status, status_version,
             current_promotion_commit_id, state_hash, created_by, updated_by)
            VALUES (:sid, :status, 0, NULL, :hash, :actor, :actor)
            ON CONFLICT (strategy_definition_id) DO NOTHING
            """
        ),
        {"sid": strategy_definition_id, "status": PROMOTION_STATE_NOT_PROMOTED, "hash": initial_hash, "actor": actor},
    )
    state = session.scalar(
        select(StrategyPromotionStateEntity)
        .where(StrategyPromotionStateEntity.strategy_definition_id == strategy_definition_id)
        .with_for_update()
    )
    assert state is not None  # INSERT ... ON CONFLICT DO NOTHING 직후이므로 항상 존재.
    return state


def run_create_promotion_commit(
    session: Session,
    strategy_definition_id: int,
    *,
    decision_package_id: int,
    human_decision_id: int,
    promotion_readiness_hash: str,
    commit_reason: str,
    confirmation_text: str,
    acknowledge_same_actor_warning: bool = False,
    actor: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if not commit_reason or not commit_reason.strip():
        raise PromotionCommitError("COMMIT_REASON_REQUIRED", "commit_reason은 필수입니다.")
    if _normalize_confirmation_text(confirmation_text) != CONFIRMATION_TEXT_REQUIRED:
        raise PromotionCommitError(
            "INVALID_CONFIRMATION", f"확인값이 올바르지 않습니다('{CONFIRMATION_TEXT_REQUIRED}'를 입력하세요)."
        )

    # 1) Strategy Definition Lock.
    definition = session.scalar(
        select(StrategyDefinitionEntity)
        .where(StrategyDefinitionEntity.strategy_id == strategy_definition_id)
        .with_for_update()
    )
    if definition is None or definition.deleted_at is not None:
        raise PromotionCommitError("NOT_FOUND", f"Strategy Definition not found: {strategy_definition_id}")

    # 1.5) Strategy Promotion State Lock(§ STEP12-16R 공식 Source of
    # Truth — 이 Lock이 동일 Strategy에 대한 동시 Commit 시도를
    # 직렬화하는 핵심 지점이다. 이 시점 이후로는 두 번째 요청이 여기서
    # 대기하다가, 첫 요청이 commit한 뒤에야 진행되어 이미 전이된 최신
    # 상태를 보게 된다).
    promotion_state = _ensure_and_lock_promotion_state(session, strategy_definition_id, actor=actor)

    # 2) Decision Package Lock + 소유 확인.
    package = session.scalar(
        select(StrategyDecisionPackageEntity)
        .where(StrategyDecisionPackageEntity.package_id == decision_package_id)
        .with_for_update()
    )
    if package is None:
        raise PromotionCommitError("PACKAGE_NOT_FOUND", f"Decision Package not found: {decision_package_id}")
    if package.strategy_id != strategy_definition_id:
        raise PromotionCommitError(
            "OWNERSHIP_MISMATCH", f"Decision Package #{decision_package_id}은 이 Strategy의 Package가 아닙니다."
        )

    # 3) Human Decision 조회 + 소유/조건 확인.
    decision = session.get(StrategyHumanDecisionEntity, human_decision_id)
    if decision is None:
        raise PromotionCommitError("DECISION_NOT_FOUND", f"Human Decision not found: {human_decision_id}")
    if decision.package_id != decision_package_id or decision.strategy_id != strategy_definition_id:
        raise PromotionCommitError(
            "OWNERSHIP_MISMATCH", f"Human Decision #{human_decision_id}은 이 Strategy/Package의 결정이 아닙니다."
        )
    if decision.decision_type != "APPROVE_FOR_PROMOTION":
        raise PromotionCommitError(
            "DECISION_TYPE_MISMATCH", f"Decision Type이 APPROVE_FOR_PROMOTION이 아닙니다(현재: {decision.decision_type})."
        )
    if not decision.promotion_ready:
        raise PromotionCommitError("PROMOTION_NOT_READY", "이 Decision은 promotion_ready=false입니다.")
    if decision.promotion_readiness_hash != promotion_readiness_hash:
        raise PromotionCommitError(
            "READINESS_HASH_MISMATCH", "요청한 promotion_readiness_hash가 Decision의 값과 일치하지 않습니다."
        )
    if decision.same_actor_warning and not acknowledge_same_actor_warning:
        raise PromotionCommitError(
            "SAME_ACTOR_WARNING_NOT_ACKNOWLEDGED",
            "Package 생성자와 결정자가 동일합니다 — acknowledge_same_actor_warning=true가 필요합니다.",
        )

    # 4) 이미 Promotion됨 여부(Idempotency 우선 확인).
    existing_for_strategy = session.scalar(
        select(StrategyPromotionCommitEntity).where(
            StrategyPromotionCommitEntity.strategy_definition_id == strategy_definition_id
        )
    )
    if existing_for_strategy is not None:
        if idempotency_key and existing_for_strategy.idempotency_key == idempotency_key:
            return _to_commit_dict(session, existing_for_strategy, idempotent_replay=True)
        if idempotency_key:
            raise PromotionCommitError(
                "IDEMPOTENCY_CONFLICT", f"idempotency_key '{idempotency_key}'가 이미 다른 Promotion Commit에 사용되었습니다."
            )
        raise PromotionCommitError(
            "ALREADY_PROMOTED", f"Strategy Definition #{strategy_definition_id}은 이미 Promotion Commit이 존재합니다."
        )
    existing_for_decision = session.scalar(
        select(StrategyPromotionCommitEntity).where(
            StrategyPromotionCommitEntity.human_decision_id == human_decision_id
        )
    )
    if existing_for_decision is not None:
        raise PromotionCommitError(
            "DUPLICATE_PROMOTION_COMMIT", f"Human Decision #{human_decision_id}에 대한 Promotion Commit이 이미 존재합니다."
        )

    # 4.5) 현재 Strategy Promotion State 확인(§ STEP12-16R 공식
    # Source of Truth) — Promotion Commit 행이 아직 없더라도 State가
    # 이미 NOT_PROMOTED가 아니면(예: 향후 STEP에서 ACTIVATION_REVIEW 등
    # 으로 더 전이된 경우) 재전이를 차단한다. 임의로 상태를 초기화하지
    # 않는다.
    if promotion_state.current_status != PROMOTION_STATE_NOT_PROMOTED:
        if promotion_state.current_status == PROMOTION_STATE_PROMOTION_COMMITTED:
            raise PromotionCommitError(
                "ALREADY_PROMOTED", f"Strategy Definition #{strategy_definition_id}은 이미 Promotion State가 PROMOTION_COMMITTED입니다."
            )
        raise PromotionCommitError(
            "PROMOTION_STATE_NOT_ELIGIBLE",
            f"Strategy Promotion State가 전이 불가 상태입니다(현재: {promotion_state.current_status}).",
        )

    # 5) Stale 재검증(원본이 최신이 아니게 됐다는 이유만으로는 Stale이
    # 아니다 — Snapshot 무결성이 깨진 경우만).
    stale, stale_reasons = check_package_staleness(session, package)
    if stale:
        raise PromotionCommitError(
            "STALE_PROMOTION_READINESS", f"Promotion Readiness가 Stale 상태입니다: {', '.join(stale_reasons)}"
        )

    # 6) Package 상태 재검증 — current effective status만 사용(생성
    # 시점 package_status만 보고 판단하지 않는다).
    if package.blocking_evidence_count > 0:
        raise PromotionCommitError("BLOCKING_EVIDENCE_EXISTS", "Blocking Evidence가 존재해 Commit할 수 없습니다.")
    if package.package_status != "READY_FOR_REVIEW":
        raise PromotionCommitError(
            "PACKAGE_NOT_PROMOTABLE", f"Package 상태가 READY_FOR_REVIEW가 아니었습니다(생성 시점: {package.package_status})."
        )

    # 7) Lifecycle/Approval 게이팅(§ 모듈 docstring — WRITE하지 않고 읽기
    # 전용으로만 사용).
    previous_lifecycle_status: str | None = None
    if definition.candidate_id is not None:
        lifecycle = session.scalar(
            select(AICandidateLifecycleEntity)
            .where(AICandidateLifecycleEntity.candidate_id == definition.candidate_id)
            .with_for_update()
        )
        if lifecycle is not None:
            previous_lifecycle_status = lifecycle.lifecycle_status
            if lifecycle.lifecycle_status in _STALE_LIFECYCLE_STATUSES:
                raise PromotionCommitError(
                    "LIFECYCLE_NOT_PROMOTABLE", f"Candidate Lifecycle 상태가 Promotion 불가 상태입니다: {lifecycle.lifecycle_status}"
                )
    if definition.approval_id is not None:
        approval = session.get(StrategyDraftApprovalEntity, int(definition.approval_id))
        if approval is not None and approval.status != "APPROVED":
            raise PromotionCommitError(
                "LIFECYCLE_NOT_PROMOTABLE", f"Approval 상태가 Promotion 불가 상태입니다: {approval.status}"
            )

    # 8) Snapshot/Hash 구성 후 저장(Atomic — 이 함수 전체가 하나의
    # Transaction, 실패 시 전부 Rollback).
    committed_at = datetime.now(timezone.utc)
    confirmation_hash = _hash(_canonical_json({"confirmation_text": _normalize_confirmation_text(confirmation_text)}))

    source_report_snapshot_payload = {
        "selected_report_ids": package.selected_report_ids,
        "selected_report_hashes": package.selected_report_hashes,
        "explainability_report_id": package.explainability_report_id,
        "explainability_input_hash": package.explainability_input_hash,
        "evidence_snapshot_hash": package.evidence_snapshot_hash,
    }
    provenance_snapshot_payload = {
        "strategy_definition_version": package.strategy_definition_version,
        "definition_hash": package.definition_hash,
        "executable_hash": package.executable_hash,
        "approval_snapshot_hash": package.approval_snapshot_hash,
        "checklist_payload": decision.checklist_payload,
        "acknowledged_warnings": decision.acknowledged_warnings_payload,
    }

    promotion_commit_hash = compute_promotion_commit_hash(
        strategy_definition_id=strategy_definition_id,
        strategy_definition_version=package.strategy_definition_version,
        definition_hash=package.definition_hash,
        executable_hash=package.executable_hash,
        approval_snapshot_hash=package.approval_snapshot_hash,
        decision_package_id=decision_package_id,
        package_input_hash=package.package_input_hash,
        human_decision_id=human_decision_id,
        decision_input_hash=decision.decision_input_hash,
        promotion_readiness_hash=promotion_readiness_hash,
        previous_lifecycle_status=previous_lifecycle_status,
        committed_lifecycle_status=COMMITTED_LIFECYCLE_STATUS,
        committed_by=actor,
        committed_at=committed_at,
        confirmation_hash=confirmation_hash,
        algorithm_version=ALGORITHM_VERSION,
    )

    commit_entity = StrategyPromotionCommitEntity(
        strategy_definition_id=strategy_definition_id,
        candidate_id=definition.candidate_id,
        strategy_request_id=definition.strategy_request_id,
        approval_id=definition.approval_id,
        decision_package_id=decision_package_id,
        human_decision_id=human_decision_id,
        previous_lifecycle_status=previous_lifecycle_status,
        committed_lifecycle_status=COMMITTED_LIFECYCLE_STATUS,
        strategy_definition_version=package.strategy_definition_version,
        definition_hash=package.definition_hash,
        executable_hash=package.executable_hash,
        approval_snapshot_hash=package.approval_snapshot_hash,
        package_input_hash=package.package_input_hash,
        decision_input_hash=decision.decision_input_hash,
        promotion_readiness_hash=promotion_readiness_hash,
        source_report_snapshot_payload=source_report_snapshot_payload,
        provenance_snapshot_payload=provenance_snapshot_payload,
        commit_reason=commit_reason,
        confirmation_hash=confirmation_hash,
        committed_by=actor,
        committed_at=committed_at,
        idempotency_key=(idempotency_key or None),
        promotion_commit_hash=promotion_commit_hash,
        algorithm_version=ALGORITHM_VERSION,
    )
    # 9~11) Commit INSERT -> Promotion State 전이 -> Promotion History
    # INSERT를 전부 같은 Transaction에서 수행한다(§ STEP12-16R 핵심 —
    # 세 가지가 전부 있어야 성공, 부분 성공 없음). IntegrityError는
    # DB 원문을 그대로 노출하지 않고 Domain Error로 변환한다.
    try:
        session.add(commit_entity)
        session.flush()  # promotion_commit_id(Identity) 확보.

        previous_status = promotion_state.current_status
        new_status = PROMOTION_STATE_PROMOTION_COMMITTED
        if not _can_transition_promotion_state(previous_status, new_status):
            # Lock을 잡은 상태에서 확인했으므로 이 경로는 이론상 도달하지
            # 않지만(§ 4.5에서 이미 차단), 방어적으로 한 번 더 검증한다.
            raise PromotionCommitError(
                "INVALID_PROMOTION_STATE_TRANSITION", f"{previous_status} -> {new_status} 전이는 허용되지 않습니다."
            )

        transitioned_at = committed_at
        new_status_version = promotion_state.status_version + 1
        state_hash = compute_promotion_state_hash(
            strategy_definition_id=strategy_definition_id,
            current_status=new_status,
            status_version=new_status_version,
            current_promotion_commit_id=int(commit_entity.promotion_commit_id),
            previous_event_hash=None,
            transitioned_at=transitioned_at,
            algorithm_version=ALGORITHM_VERSION,
        )
        promotion_state.current_status = new_status
        promotion_state.status_version = new_status_version
        promotion_state.current_promotion_commit_id = int(commit_entity.promotion_commit_id)
        promotion_state.state_hash = state_hash
        promotion_state.updated_by = actor

        event_hash = compute_promotion_state_event_hash(
            strategy_definition_id=strategy_definition_id,
            promotion_commit_id=int(commit_entity.promotion_commit_id),
            previous_status=previous_status,
            new_status=new_status,
            human_decision_id=human_decision_id,
            decision_package_id=decision_package_id,
            actor=actor,
            occurred_at=transitioned_at,
            transition_reason=commit_reason,
            algorithm_version=ALGORITHM_VERSION,
        )
        history_entity = StrategyPromotionHistoryEntity(
            strategy_definition_id=strategy_definition_id,
            promotion_commit_id=int(commit_entity.promotion_commit_id),
            previous_status=previous_status,
            new_status=new_status,
            transition_reason=commit_reason,
            human_decision_id=human_decision_id,
            decision_package_id=decision_package_id,
            actor=actor,
            event_hash=event_hash,
            occurred_at=transitioned_at,
            algorithm_version=ALGORITHM_VERSION,
            metadata_payload={"promotion_commit_hash": promotion_commit_hash},
        )
        session.add(history_entity)
        session.flush()
        session.commit()
    except IntegrityError:
        # § STEP12-16R — DB Unique Constraint 경합(동시 요청이 Lock 획득
        # 순서상 여기까지 왔을 가능성 등)을 Domain Error로 변환한다.
        # DB 원문 오류를 외부에 그대로 노출하지 않는다.
        session.rollback()
        conflict = session.scalar(
            select(StrategyPromotionCommitEntity).where(
                StrategyPromotionCommitEntity.strategy_definition_id == strategy_definition_id
            )
        )
        if conflict is not None:
            if idempotency_key and conflict.idempotency_key == idempotency_key:
                return _to_commit_dict(session, conflict, idempotent_replay=True)
            raise PromotionCommitError(
                "ALREADY_PROMOTED", f"Strategy Definition #{strategy_definition_id}은 이미 Promotion Commit이 존재합니다."
            ) from None
        decision_conflict = session.scalar(
            select(StrategyPromotionCommitEntity).where(
                StrategyPromotionCommitEntity.human_decision_id == human_decision_id
            )
        )
        if decision_conflict is not None:
            raise PromotionCommitError(
                "DUPLICATE_PROMOTION_COMMIT", f"Human Decision #{human_decision_id}에 대한 Promotion Commit이 이미 존재합니다."
            ) from None
        raise PromotionCommitError(
            "DUPLICATE_PROMOTION_HISTORY", "동일 Promotion Commit에 대한 전이 History가 이미 존재합니다."
        ) from None

    session.refresh(commit_entity)
    return _to_commit_dict(session, commit_entity, idempotent_replay=False)


def _to_commit_dict(session: Session, commit: StrategyPromotionCommitEntity, *, idempotent_replay: bool) -> dict[str, Any]:
    """§ STEP12-16R — 응답 필드 의미 수정. `previous_lifecycle_status`/
    `committed_lifecycle_status`는 하위 호환을 위해 그대로 남기되(값도
    그대로), 실제로는 Candidate Lifecycle이 아니라는 점을 명확히 하기
    위해 `candidate_lifecycle_status`(현재 실제 Candidate Lifecycle
    값, Commit이 이를 전이시키지 않았으므로 조회 시점 최신값)와
    `strategy_promotion_status`/`previous_promotion_status`/
    `current_promotion_status`(공식 Strategy Promotion State/History
    기준)를 별도 필드로 노출한다. `current_lifecycle_status`(기존
    필드)는 이름이 오해를 유발하므로 deprecated로 유지만 한다."""
    promotion_state = session.scalar(
        select(StrategyPromotionStateEntity).where(
            StrategyPromotionStateEntity.strategy_definition_id == commit.strategy_definition_id
        )
    )
    candidate_lifecycle_status: str | None = None
    if commit.candidate_id is not None:
        lifecycle = session.scalar(
            select(AICandidateLifecycleEntity).where(AICandidateLifecycleEntity.candidate_id == commit.candidate_id)
        )
        if lifecycle is not None:
            candidate_lifecycle_status = lifecycle.lifecycle_status
    history = session.scalar(
        select(StrategyPromotionHistoryEntity).where(
            StrategyPromotionHistoryEntity.promotion_commit_id == commit.promotion_commit_id
        )
    )

    return {
        "promotion_commit_id": int(commit.promotion_commit_id),
        "strategy_definition_id": commit.strategy_definition_id,
        "candidate_id": commit.candidate_id,
        "strategy_request_id": commit.strategy_request_id,
        "approval_id": commit.approval_id,
        "decision_package_id": commit.decision_package_id,
        "human_decision_id": commit.human_decision_id,
        # deprecated(§ STEP12-16R) — 이름과 달리 실제 Candidate Lifecycle을
        # 전이시킨 적이 없다. candidate_lifecycle_status/
        # strategy_promotion_status를 사용하라.
        "previous_lifecycle_status": commit.previous_lifecycle_status,
        "committed_lifecycle_status": commit.committed_lifecycle_status,
        "current_lifecycle_status": commit.committed_lifecycle_status,
        "candidate_lifecycle_status": candidate_lifecycle_status,
        "strategy_promotion_status": promotion_state.current_status if promotion_state else None,
        "previous_promotion_status": history.previous_status if history else None,
        "current_promotion_status": history.new_status if history else None,
        "promotion_state_version": promotion_state.status_version if promotion_state else None,
        "strategy_definition_version": commit.strategy_definition_version,
        "definition_hash": commit.definition_hash,
        "executable_hash": commit.executable_hash,
        "approval_snapshot_hash": commit.approval_snapshot_hash,
        "package_input_hash": commit.package_input_hash,
        "decision_input_hash": commit.decision_input_hash,
        "promotion_readiness_hash": commit.promotion_readiness_hash,
        "source_report_snapshot": commit.source_report_snapshot_payload,
        "provenance_snapshot": commit.provenance_snapshot_payload,
        "commit_reason": commit.commit_reason,
        "confirmation_hash": commit.confirmation_hash,
        "committed_by": commit.committed_by,
        "committed_at": commit.committed_at,
        "promotion_commit_hash": commit.promotion_commit_hash,
        "algorithm_version": commit.algorithm_version,
        "promotion_committed": True,
        "activation_status": FIXED_ACTIVATION_STATUS,
        "deployment_status": FIXED_DEPLOYMENT_STATUS,
        "runtime_status": FIXED_RUNTIME_STATUS,
        "next_action": FIXED_NEXT_ACTION,
        "idempotent_replay": idempotent_replay,
    }


def get_promotion_commit(
    session: Session, commit_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    commit = session.get(StrategyPromotionCommitEntity, commit_id)
    if commit is None:
        raise PromotionCommitError("NOT_FOUND", f"Promotion Commit not found: {commit_id}")
    if strategy_definition_id is not None and commit.strategy_definition_id != strategy_definition_id:
        raise PromotionCommitError("NOT_FOUND", f"Promotion Commit not found: {commit_id}")
    return _to_commit_dict(session, commit, idempotent_replay=False)


def list_promotion_commits(session: Session, strategy_definition_id: int) -> list[dict[str, Any]]:
    commits = session.scalars(
        select(StrategyPromotionCommitEntity)
        .where(StrategyPromotionCommitEntity.strategy_definition_id == strategy_definition_id)
        .order_by(StrategyPromotionCommitEntity.promotion_commit_id.desc())
    )
    return [_to_commit_dict(session, c, idempotent_replay=False) for c in commits]


def get_promotion_commit_provenance(
    session: Session, commit_id: int, *, strategy_definition_id: int | None = None
) -> dict[str, Any]:
    commit = get_promotion_commit(session, commit_id, strategy_definition_id=strategy_definition_id)
    return {
        "promotion_commit_id": commit["promotion_commit_id"],
        "source_report_snapshot": commit["source_report_snapshot"],
        "provenance_snapshot": commit["provenance_snapshot"],
        "promotion_commit_hash": commit["promotion_commit_hash"],
    }


def _to_history_dict(history: StrategyPromotionHistoryEntity) -> dict[str, Any]:
    return {
        "history_id": int(history.promotion_history_id),
        "strategy_definition_id": history.strategy_definition_id,
        "promotion_commit_id": history.promotion_commit_id,
        "previous_status": history.previous_status,
        "new_status": history.new_status,
        "transition_reason": history.transition_reason,
        "human_decision_id": history.human_decision_id,
        "decision_package_id": history.decision_package_id,
        "actor": history.actor,
        "event_hash": history.event_hash,
        "occurred_at": history.occurred_at,
        "algorithm_version": history.algorithm_version,
    }


def get_promotion_history(session: Session, strategy_definition_id: int) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(StrategyPromotionHistoryEntity)
        .where(StrategyPromotionHistoryEntity.strategy_definition_id == strategy_definition_id)
        .order_by(
            StrategyPromotionHistoryEntity.occurred_at.asc(),
            StrategyPromotionHistoryEntity.promotion_history_id.asc(),
        )
    )
    return [_to_history_dict(h) for h in rows]


def get_promotion_state(session: Session, strategy_definition_id: int) -> dict[str, Any]:
    state = session.scalar(
        select(StrategyPromotionStateEntity).where(
            StrategyPromotionStateEntity.strategy_definition_id == strategy_definition_id
        )
    )
    if state is None:
        # 아직 Promotion Commit을 한 번도 시도하지 않은 Strategy는 행이
        # 없다 — 개념상 NOT_PROMOTED(§ STEP12-16R "Strategy Definition당
        # 공식 현재 Promotion State 1개"의 가상 기본값)로 취급한다.
        return {
            "strategy_definition_id": strategy_definition_id,
            "current_status": PROMOTION_STATE_NOT_PROMOTED,
            "status_version": 0,
            "current_promotion_commit_id": None,
            "state_hash": None,
        }
    return {
        "strategy_definition_id": state.strategy_definition_id,
        "current_status": state.current_status,
        "status_version": state.status_version,
        "current_promotion_commit_id": state.current_promotion_commit_id,
        "state_hash": state.state_hash,
    }


def get_promotion_commit_history(session: Session, strategy_definition_id: int) -> dict[str, Any]:
    """§ STEP12-16R — 기존에는 Promotion Commit 목록만 반환했으나(취소·
    되돌리기를 구현하지 않아 사실상 0~1개), 실제 Promotion State 전이
    History로 교체한다. `occurred_at ASC, history_id ASC`로 결정적
    정렬(§ 명세)."""
    history = get_promotion_history(session, strategy_definition_id)
    return {"strategy_definition_id": strategy_definition_id, "history": history}


def get_promotion_status(session: Session, strategy_definition_id: int) -> dict[str, Any]:
    from stock_platform.ai.strategy_draft_approval.decision_package import (
        get_promotion_readiness,
    )

    readiness = get_promotion_readiness(session, strategy_definition_id)
    state = get_promotion_state(session, strategy_definition_id)
    commit = session.scalar(
        select(StrategyPromotionCommitEntity).where(
            StrategyPromotionCommitEntity.strategy_definition_id == strategy_definition_id
        )
    )
    candidate_lifecycle_status: str | None = None
    definition = session.get(StrategyDefinitionEntity, strategy_definition_id)
    if definition is not None and definition.candidate_id is not None:
        lifecycle = session.scalar(
            select(AICandidateLifecycleEntity).where(AICandidateLifecycleEntity.candidate_id == definition.candidate_id)
        )
        if lifecycle is not None:
            candidate_lifecycle_status = lifecycle.lifecycle_status

    if commit is not None:
        return {
            "promotion_ready": True,
            "promotion_committed": True,
            "promotion_commit_id": int(commit.promotion_commit_id),
            "strategy_promotion_status": state["current_status"],
            "candidate_lifecycle_status": candidate_lifecycle_status,
            "promotion_state_version": state["status_version"],
            "stale": False,
            "stale_after_decision": False,
            "activation_status": FIXED_ACTIVATION_STATUS,
            "deployment_status": FIXED_DEPLOYMENT_STATUS,
            "runtime_status": FIXED_RUNTIME_STATUS,
            "next_action": FIXED_NEXT_ACTION,
        }
    return {
        "promotion_ready": readiness["ready"],
        "promotion_committed": False,
        "promotion_commit_id": None,
        "strategy_promotion_status": state["current_status"],
        "candidate_lifecycle_status": candidate_lifecycle_status,
        "promotion_state_version": state["status_version"],
        "stale": readiness["stale_after_decision"],
        "stale_after_decision": readiness["stale_after_decision"],
        "activation_status": FIXED_ACTIVATION_STATUS,
        "deployment_status": FIXED_DEPLOYMENT_STATUS,
        "runtime_status": FIXED_RUNTIME_STATUS,
        "next_action": readiness["next_action"],
    }
