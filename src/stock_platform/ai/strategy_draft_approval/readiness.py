"""STEP 12-5 — Strategy Definition Backtest Readiness & Provenance Chain 검증.

새 Entity/Table/API DTO를 만들지 않는다 — 기존 STEP12-2-1(Draft)/
STEP12-2-2(Generation Run/Attempt)/STEP12-3(Approval/Definition) 엔티티만
읽기 전용으로 조회해 다음 두 가지를 검증한다.

1. `validate_provenance()` — Candidate -> Draft -> Approval -> Strategy
   Definition 4단 연결이 서로 내부적으로 일치하는지(교차 참조 무결성)만
   검증한다. **현재** Candidate 상태/fingerprint가 승인 시점과 같은지는
   검증하지 않는다 — Snapshot은 승인 시점에 고정된 불변 기록이며, 이후
   Candidate가 철회/변경되어도 이미 승인된 Definition의 재현 가능성은
   유지되어야 하기 때문이다(STEP12-3의 "승인 후 불변" 설계와 일관).
2. `check_readiness()` — Provenance Chain 검증 + Definition 활성 상태 +
   Hash 무결성 + Backtest에 필요한 필드 완전성을 종합해 Backtest 가능
   여부를 판정한다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_lifecycle.entities import AICandidateLifecycleEntity
from stock_platform.ai.strategy_draft.entities import StrategyDraftEntity
from stock_platform.ai.strategy_draft_approval.entities import (
    StrategyDraftApprovalEntity,
)
from stock_platform.ai.strategy_draft_generation.entities import (
    StrategyDraftGenerationAttemptEntity,
    StrategyDraftGenerationRunEntity,
)
from stock_platform.ai.strategy_request.entities import StrategyRequestEntity
from stock_platform.strategy_deployment.definition_entities import (
    StrategyDefinitionEntity,
)

# Backtest가 최소한으로 필요로 하는 구조화 필드(STEP12-3 parameter_payload
# 매핑과 동일한 키 — 여기서 새 스키마를 만들지 않고 그대로 재사용한다).
_REQUIRED_PAYLOAD_FIELDS = (
    "entry_rule",
    "exit_rule",
    "stop_loss_rule",
    "take_profit_rule",
    "position_sizing_rule",
    "timeframe",
)


class ReadinessError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _require_definition(session: Session, strategy_definition_id: int) -> StrategyDefinitionEntity:
    row = session.get(StrategyDefinitionEntity, int(strategy_definition_id))
    if row is None:
        raise ReadinessError(
            "NOT_FOUND", f"Strategy Definition not found: {strategy_definition_id}"
        )
    return row


def validate_provenance(session: Session, strategy_definition_id: int) -> dict[str, Any]:
    """Candidate -> Draft -> Approval -> Strategy Definition 체인을 추적하고
    교차 참조 무결성을 검증한다. 실패해도 예외를 던지지 않고 `valid`
    플래그 + `failures` 목록으로 반환한다(호출자가 Readiness 판정에
    합성해서 쓰거나, 단독 조회 API로도 그대로 노출하기 위함)."""

    definition = _require_definition(session, strategy_definition_id)
    failures: list[str] = []
    chain: dict[str, Any] = {
        "strategy_definition_id": int(definition.strategy_id),
        "definition_hash": definition.definition_hash,
        "definition_version": definition.definition_version,
        "approval_id": definition.approval_id,
        "source_draft_id": definition.source_draft_id,
        "strategy_request_id": definition.strategy_request_id,
        "candidate_id": definition.candidate_id,
        "candidate_fingerprint": definition.candidate_fingerprint,
        "generation_run_id": None,
        "generation_attempt_id": None,
    }

    if definition.source_draft_id is None:
        failures.append("NOT_DRAFT_DERIVED — 이 Definition은 Draft 승인 경로로 생성되지 않았습니다.")
        return {"valid": False, "failures": failures, "chain": chain}

    approval = (
        session.get(StrategyDraftApprovalEntity, int(definition.approval_id))
        if definition.approval_id is not None
        else None
    )
    if approval is None:
        failures.append("APPROVAL_MISSING — approval_id가 없거나 연결된 Approval을 찾을 수 없습니다.")
    else:
        chain["generation_run_id"] = approval.generation_run_id
        chain["generation_attempt_id"] = approval.generation_attempt_id
        if int(approval.strategy_definition_id or 0) != int(definition.strategy_id):
            failures.append("APPROVAL_DEFINITION_MISMATCH — Approval이 가리키는 Definition이 다릅니다.")
        if approval.status not in {"APPROVED", "REVOKED", "SUPERSEDED"}:
            failures.append(f"APPROVAL_STATUS_UNEXPECTED — {approval.status}")
        if int(approval.draft_id) != int(definition.source_draft_id):
            failures.append("APPROVAL_DRAFT_MISMATCH — Approval의 draft_id가 Definition과 다릅니다.")
        if approval.candidate_fingerprint_at_approval != definition.candidate_fingerprint:
            failures.append(
                "APPROVAL_FINGERPRINT_MISMATCH — Approval 승인 시점 fingerprint와 "
                "Definition의 fingerprint가 다릅니다."
            )

    draft = session.get(StrategyDraftEntity, int(definition.source_draft_id))
    if draft is None:
        failures.append("DRAFT_MISSING — source_draft_id에 해당하는 Draft를 찾을 수 없습니다.")
    else:
        if int(draft.strategy_request_id) != int(definition.strategy_request_id or 0):
            failures.append("DRAFT_REQUEST_MISMATCH — Draft의 strategy_request_id가 다릅니다.")
        if draft.candidate_fingerprint != definition.candidate_fingerprint:
            failures.append(
                "DRAFT_FINGERPRINT_MISMATCH — Draft의 candidate_fingerprint가 "
                "Definition과 다릅니다."
            )
        if definition.source_draft_version is not None and int(draft.version) != int(
            definition.source_draft_version
        ):
            failures.append("DRAFT_VERSION_MISMATCH — Draft version이 Definition 기록과 다릅니다.")
        if draft.llm_provider is not None:
            # AI 생성 Draft라면 Generation Run까지 추적한다.
            run = session.scalar(
                select(StrategyDraftGenerationRunEntity).where(
                    StrategyDraftGenerationRunEntity.draft_id == int(draft.draft_id)
                )
            )
            if run is None:
                failures.append("GENERATION_RUN_MISSING — AI 생성 Draft인데 Generation Run이 없습니다.")
            else:
                if approval is not None and approval.generation_run_id is not None and int(
                    approval.generation_run_id
                ) != int(run.generation_run_id):
                    failures.append("GENERATION_RUN_MISMATCH — Approval이 기록한 Run과 다릅니다.")
                attempt = (
                    session.get(
                        StrategyDraftGenerationAttemptEntity,
                        int(approval.generation_attempt_id),
                    )
                    if approval is not None and approval.generation_attempt_id is not None
                    else None
                )
                if approval is not None and approval.generation_attempt_id is not None and attempt is None:
                    failures.append("GENERATION_ATTEMPT_MISSING — Approval이 기록한 Attempt가 없습니다.")

    request = (
        session.get(StrategyRequestEntity, int(definition.strategy_request_id))
        if definition.strategy_request_id is not None
        else None
    )
    if request is None:
        failures.append("STRATEGY_REQUEST_MISSING — strategy_request_id에 해당하는 Request가 없습니다.")
    elif definition.candidate_id is not None and int(request.candidate_id) != int(
        definition.candidate_id
    ):
        failures.append("REQUEST_CANDIDATE_MISMATCH — Request의 candidate_id가 Definition과 다릅니다.")

    # candidate_id는 candidate_lifecycle의 PK(lifecycle_id)가 아니라
    # UniqueConstraint 컬럼이므로 session.get()이 아닌 별도 조회가 필요하다
    # (STEP12-1A에서 동일한 실수를 한 번 겪은 패턴 — validate_supersession_pair).
    candidate = (
        session.scalar(
            select(AICandidateLifecycleEntity).where(
                AICandidateLifecycleEntity.candidate_id == int(definition.candidate_id)
            )
        )
        if definition.candidate_id is not None
        else None
    )
    if candidate is None:
        failures.append("CANDIDATE_MISSING — candidate_id에 해당하는 Candidate를 찾을 수 없습니다.")

    return {"valid": len(failures) == 0, "failures": failures, "chain": chain}


def check_readiness(session: Session, strategy_definition_id: int) -> dict[str, Any]:
    """Backtest Readiness 종합 판정. 예외를 던지지 않고 항상
    `{"ready": bool, "checks": {...}, "chain": {...}, "failure_reasons": [...]}`를
    반환한다(NOT_FOUND만 ReadinessError로 raise — 조회 대상 자체가 없음)."""

    definition = _require_definition(session, strategy_definition_id)
    reasons: list[str] = []
    checks: dict[str, bool] = {}

    checks["is_active"] = bool(definition.is_active)
    if not checks["is_active"]:
        reasons.append("Definition이 비활성 상태입니다(취소/대체됨).")

    from stock_platform.ai.strategy_draft_approval.service import _definition_hash

    recomputed = _definition_hash(definition)
    checks["hash_valid"] = recomputed == definition.definition_hash
    if not checks["hash_valid"]:
        reasons.append("definition_hash가 현재 내용과 일치하지 않습니다(변조 의심).")

    checks["schema_version_present"] = bool(definition.schema_version)
    if not checks["schema_version_present"]:
        reasons.append("schema_version이 없습니다.")

    payload = definition.parameter_payload or {}
    missing_fields = [f for f in _REQUIRED_PAYLOAD_FIELDS if not payload.get(f)]
    checks["payload_complete"] = len(missing_fields) == 0
    if missing_fields:
        reasons.append(f"필수 필드 누락: {', '.join(missing_fields)}")

    provenance = validate_provenance(session, strategy_definition_id)
    checks["provenance_valid"] = provenance["valid"]
    if not provenance["valid"]:
        reasons.extend(provenance["failures"])

    ready = all(checks.values())
    return {
        "ready": ready,
        "checks": checks,
        "chain": provenance["chain"],
        "failure_reasons": reasons,
    }
