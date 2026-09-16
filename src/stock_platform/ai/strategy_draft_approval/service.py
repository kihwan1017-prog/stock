"""STEP 12-3 — Strategy Draft 관리자 최종 승인 서비스.

승인은 반드시 단일 짧은 DB 트랜잭션 안에서 수행하며, 고정 잠금 순서를
따른다(§5):
    1. StrategyRequestEntity FOR UPDATE
    2. AICandidateLifecycleEntity FOR UPDATE
    3. StrategyDraftEntity FOR UPDATE
    4. 기존 활성 Approval(동일 draft_id / 동일 strategy_request_id) FOR UPDATE
    5. (승인 시에만) 새로 생성하는 StrategyDefinitionEntity

기존 trading.strategy_definition을 재사용한다(신규 중복 테이블 없음) —
Draft 승인으로 생성된 행은 `source_draft_id`가 채워지며, 이후
ownership.py의 `assert_strategy_writable`/`admin_approve`/
`admin_set_visibility`/`admin_set_active`가 이 행을 직접 수정하지
못하도록 차단한다(불변 정책).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_lifecycle.entities import AICandidateLifecycleEntity
from stock_platform.ai.strategy_draft.constants import (
    ELIGIBLE_STRATEGY_REQUEST_STATUS,
)
from stock_platform.ai.strategy_draft.entities import StrategyDraftEntity
from stock_platform.ai.strategy_draft_approval.constants import (
    DEFINITION_SCHEMA_VERSION,
    REASON_MAX_LENGTH,
)
from stock_platform.ai.strategy_draft_approval.entities import (
    StrategyDraftApprovalEntity,
    StrategyDraftApprovalHistoryEntity,
)
from stock_platform.ai.strategy_draft_approval.validation import (
    DraftApprovalValidationError,
    validate_draft_for_approval,
)
from stock_platform.ai.strategy_draft_generation.entities import (
    StrategyDraftGenerationAttemptEntity,
    StrategyDraftGenerationRunEntity,
)
from stock_platform.ai.strategy_request.constants import (
    ELIGIBLE_CANDIDATE_LIFECYCLE_STATUSES,
)
from stock_platform.ai.strategy_request.entities import StrategyRequestEntity
from stock_platform.strategy_deployment.definition_entities import (
    StrategyDefinitionEntity,
)


class StrategyDraftApprovalError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _draft_content_hash(draft: StrategyDraftEntity) -> str:
    payload = {
        "title": draft.title,
        "summary": draft.summary,
        "entry_rule": draft.entry_rule,
        "exit_rule": draft.exit_rule,
        "stop_loss_rule": draft.stop_loss_rule,
        "take_profit_rule": draft.take_profit_rule,
        "position_sizing_rule": draft.position_sizing_rule,
        "timeframe": draft.timeframe,
        "market_type": draft.market_type,
        "risk_parameters": draft.risk_parameters,
        "indicator_configuration": draft.indicator_configuration,
    }
    return _hash(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str))


# trading.strategy_definition(STEP8-3)의 기존 market_type CHECK 제약은
# {'STOCK','CRYPTO','ALL'}만 허용한다. Draft의 market_type 어휘(STEP12-2-2,
# ALLOWED_MARKET_TYPES={'KR_STOCK','CRYPTO'})는 더 세분화돼 있으므로,
# Definition 생성 시 이 값으로 매핑한다(기존 제약을 느슨하게 바꾸는 대신
# 매핑) — 원본 값은 parameter_payload에 그대로 보존해 손실이 없다.
_MARKET_TYPE_TO_DEFINITION = {
    "KR_STOCK": "STOCK",
    "CRYPTO": "CRYPTO",
}


def _map_market_type_for_definition(draft_market_type: str) -> str:
    return _MARKET_TYPE_TO_DEFINITION.get((draft_market_type or "").upper(), "STOCK")


def _definition_hash(definition: StrategyDefinitionEntity) -> str:
    payload = {
        "strategy_code": definition.strategy_code,
        "name": definition.name,
        "description": definition.description,
        "market_type": definition.market_type,
        "parameter_payload": definition.parameter_payload,
        "source_draft_id": definition.source_draft_id,
        "source_draft_version": definition.source_draft_version,
        "source_draft_revision": definition.source_draft_revision,
    }
    return _hash(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str))


def _approval_to_dict(row: StrategyDraftApprovalEntity) -> dict[str, Any]:
    return {
        "approval_id": int(row.approval_id),
        "draft_id": int(row.draft_id),
        "strategy_request_id": int(row.strategy_request_id),
        "candidate_id": int(row.candidate_id),
        "strategy_definition_id": row.strategy_definition_id,
        "generation_run_id": row.generation_run_id,
        "generation_attempt_id": row.generation_attempt_id,
        "status": row.status,
        "draft_version": row.draft_version,
        "draft_revision": row.draft_revision,
        "candidate_fingerprint_at_approval": row.candidate_fingerprint_at_approval,
        "candidate_provenance_fingerprint": row.candidate_provenance_fingerprint,
        "provider": row.provider,
        "model": row.model,
        "draft_content_hash": row.draft_content_hash,
        "definition_hash": row.definition_hash,
        "schema_version": row.schema_version,
        "reason": row.reason,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at,
        "revoked_reason": row.revoked_reason,
        "revoked_by": row.revoked_by,
        "revoked_at": row.revoked_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _history_to_dict(row: StrategyDraftApprovalHistoryEntity) -> dict[str, Any]:
    return {
        "history_id": int(row.history_id),
        "approval_id": int(row.approval_id),
        "action": row.action,
        "previous_status": row.previous_status,
        "new_status": row.new_status,
        "reason": row.reason,
        "actor": row.actor,
        "draft_version": row.draft_version,
        "draft_revision": row.draft_revision,
        "strategy_definition_id": row.strategy_definition_id,
        "metadata_hash": row.metadata_hash,
        "correlation_id": row.correlation_id,
        "created_at": row.created_at,
    }


def _require_reason(reason: str | None) -> str:
    cleaned = (reason or "").strip()
    if not cleaned:
        raise StrategyDraftApprovalError("REASON_REQUIRED", "사유(reason)는 필수입니다.")
    return cleaned[:REASON_MAX_LENGTH]


class StrategyDraftApprovalService:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 승인
    # ------------------------------------------------------------------
    def approve(
        self,
        draft_id: int,
        *,
        actor: str,
        reason: str,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        clean_reason = _require_reason(reason)
        key = (idempotency_key or "").strip() or uuid.uuid4().hex

        replay = self._session.scalar(
            select(StrategyDraftApprovalEntity).where(
                StrategyDraftApprovalEntity.draft_id == int(draft_id),
                StrategyDraftApprovalEntity.idempotency_key == key,
            )
        )
        if replay is not None:
            return {**_approval_to_dict(replay), "idempotent_replay": True}

        preview = self._session.get(StrategyDraftEntity, int(draft_id))
        if preview is None:
            raise StrategyDraftApprovalError("NOT_FOUND", f"Strategy Draft not found: {draft_id}")

        # ---- 잠금 순서: request -> candidate -> draft -> 기존 활성 Approval ----
        request = self._session.scalar(
            select(StrategyRequestEntity)
            .where(StrategyRequestEntity.strategy_request_id == preview.strategy_request_id)
            .with_for_update()
        )
        if request is None:
            raise StrategyDraftApprovalError(
                "STRATEGY_REQUEST_NOT_FOUND",
                f"Strategy Request not found: {preview.strategy_request_id}",
            )
        if request.status != ELIGIBLE_STRATEGY_REQUEST_STATUS:
            raise StrategyDraftApprovalError(
                "STRATEGY_REQUEST_NOT_APPROVED",
                f"APPROVED 상태의 Strategy Request만 대상입니다. 현재: {request.status}",
            )

        candidate = self._session.scalar(
            select(AICandidateLifecycleEntity)
            .where(AICandidateLifecycleEntity.candidate_id == int(request.candidate_id))
            .with_for_update()
        )
        if candidate is None:
            raise StrategyDraftApprovalError(
                "CANDIDATE_NOT_FOUND", f"Candidate not found: {request.candidate_id}"
            )
        if candidate.lifecycle_status not in ELIGIBLE_CANDIDATE_LIFECYCLE_STATUSES:
            raise StrategyDraftApprovalError(
                "CANDIDATE_NOT_ACTIVE",
                f"ACTIVE 상태 Candidate만 승인 가능합니다. 현재: {candidate.lifecycle_status}",
            )
        if (
            request.candidate_fingerprint_at_review is None
            or candidate.source_fingerprint != request.candidate_fingerprint_at_review
        ):
            raise StrategyDraftApprovalError(
                "CANDIDATE_FINGERPRINT_CHANGED",
                "Strategy Request 승인 시점과 현재 Candidate fingerprint가 다릅니다.",
            )

        draft = self._session.scalar(
            select(StrategyDraftEntity)
            .where(StrategyDraftEntity.draft_id == int(draft_id))
            .with_for_update()
        )
        if draft is None:
            raise StrategyDraftApprovalError("NOT_FOUND", f"Strategy Draft not found: {draft_id}")
        if draft.status != "DRAFT":
            raise StrategyDraftApprovalError(
                "DRAFT_STATUS_NOT_APPROVABLE",
                f"DRAFT 상태의 Draft만 승인할 수 있습니다. 현재: {draft.status}",
            )
        if draft.candidate_fingerprint != candidate.source_fingerprint:
            raise StrategyDraftApprovalError(
                "CANDIDATE_FINGERPRINT_CHANGED",
                "Draft 생성 시점과 현재 Candidate fingerprint가 다릅니다.",
            )

        existing_active_for_draft = self._session.scalar(
            select(StrategyDraftApprovalEntity)
            .where(
                StrategyDraftApprovalEntity.draft_id == int(draft_id),
                StrategyDraftApprovalEntity.status == "APPROVED",
            )
            .with_for_update()
        )
        if existing_active_for_draft is not None:
            raise StrategyDraftApprovalError(
                "ALREADY_APPROVED", f"이미 승인된 Draft입니다: {draft_id}"
            )

        prior_active_for_request = self._session.scalar(
            select(StrategyDraftApprovalEntity)
            .where(
                StrategyDraftApprovalEntity.strategy_request_id
                == int(request.strategy_request_id),
                StrategyDraftApprovalEntity.status == "APPROVED",
            )
            .with_for_update()
        )

        # ---- AI 생성 Draft라면 Generation Run/Attempt 검증 ----
        # mock 라벨만 있고 Generation Run이 없으면 수동 Draft로 본다.
        # (LIVE 적격으로 보지 않음. mock 신호를 실주문에 쓰지 않음.)
        generation_run: StrategyDraftGenerationRunEntity | None = None
        attempt: StrategyDraftGenerationAttemptEntity | None = None
        provider_key = (draft.llm_provider or "").strip().lower()
        if provider_key:
            generation_run = self._session.scalar(
                select(StrategyDraftGenerationRunEntity)
                .where(StrategyDraftGenerationRunEntity.draft_id == int(draft_id))
                .with_for_update()
            )
            if generation_run is None:
                if provider_key != "mock":
                    raise StrategyDraftApprovalError(
                        "DRAFT_RUN_MISMATCH",
                        "이 Draft를 생성한 Generation Run을 찾을 수 없습니다.",
                    )
            else:
                if generation_run.status != "SUCCEEDED":
                    raise StrategyDraftApprovalError(
                        "GENERATION_NOT_SUCCEEDED",
                        f"Generation Run이 SUCCEEDED 상태가 아닙니다: {generation_run.status}",
                    )
                if int(generation_run.draft_id or 0) != int(draft_id):
                    raise StrategyDraftApprovalError(
                        "DRAFT_RUN_MISMATCH",
                        "Generation Run의 draft_id가 일치하지 않습니다.",
                    )
                attempt = self._session.scalar(
                    select(StrategyDraftGenerationAttemptEntity)
                    .where(
                        StrategyDraftGenerationAttemptEntity.generation_run_id
                        == generation_run.generation_run_id,
                        StrategyDraftGenerationAttemptEntity.status == "SUCCEEDED",
                    )
                    .order_by(StrategyDraftGenerationAttemptEntity.attempt_no.desc())
                    .limit(1)
                )
                if attempt is None:
                    raise StrategyDraftApprovalError(
                        "NO_SUCCESSFUL_ATTEMPT", "성공한 Attempt가 없습니다."
                    )

        # ---- Structured Output 재검증(§12) ----
        draft_dict = {
            "market_type": draft.market_type,
            "timeframe": draft.timeframe,
            "entry_rule": draft.entry_rule,
            "exit_rule": draft.exit_rule,
            "stop_loss_rule": draft.stop_loss_rule,
            "take_profit_rule": draft.take_profit_rule,
            "position_sizing_rule": draft.position_sizing_rule,
            "risk_parameters": draft.risk_parameters,
            "indicator_configuration": draft.indicator_configuration,
        }
        try:
            validate_draft_for_approval(draft_dict)
        except DraftApprovalValidationError as exc:
            raise StrategyDraftApprovalError(exc.code, exc.message) from exc

        # ---- 여기까지 모든 검증 통과 — 이제부터 실제로 변경을 만든다 ----
        # STEP12-4 §3 — Definition Version 증가 정책: 동일 Strategy Request를
        # 대체하는 새 승인이면 이전 활성 Definition의 definition_version+1을
        # 물려받는다(같은 Request 계보의 Snapshot 이력을 버전으로 추적).
        # 완전히 새로운 Request 계보라면 1부터 시작한다.
        next_definition_version = 1
        if prior_active_for_request is not None and int(
            prior_active_for_request.draft_id
        ) != int(draft_id):
            prior_definition = (
                self._session.get(
                    StrategyDefinitionEntity,
                    int(prior_active_for_request.strategy_definition_id),
                )
                if prior_active_for_request.strategy_definition_id is not None
                else None
            )
            if prior_definition is not None and prior_definition.definition_version:
                next_definition_version = int(prior_definition.definition_version) + 1
            self._supersede(prior_active_for_request, actor=actor, correlation_id=correlation_id)

        owner_user_id = int(request.user_id)
        parameter_payload = {
            "entry_rule": _safe_json(draft.entry_rule),
            "exit_rule": _safe_json(draft.exit_rule),
            "stop_loss_rule": _safe_json(draft.stop_loss_rule),
            "take_profit_rule": _safe_json(draft.take_profit_rule),
            "position_sizing_rule": _safe_json(draft.position_sizing_rule),
            "timeframe": draft.timeframe,
            "indicator_configuration": draft.indicator_configuration or {},
            "risk_parameters": draft.risk_parameters or {},
            # Definition.market_type은 STEP8-3 어휘(STOCK/CRYPTO/ALL)로
            # 매핑되므로, Draft 원본 market_type 값은 여기에 보존한다.
            "source_market_type": draft.market_type,
        }
        stamp = _utcnow().strftime("%Y%m%d%H%M%S")
        definition = StrategyDefinitionEntity(
            strategy_code=f"draft_{draft.draft_id}_v{draft.version}r{draft.revision}_{stamp}",
            name=draft.title,
            description=draft.summary,
            market_type=_map_market_type_for_definition(draft.market_type),
            owner_type="USER",
            user_id=owner_user_id,
            visibility="PRIVATE",
            is_active=True,
            parameter_payload=parameter_payload,
            created_by=actor,
            updated_by=actor,
            approved_by=actor,
            approved_at=_utcnow(),
            source_draft_id=int(draft.draft_id),
            source_draft_version=int(draft.version),
            source_draft_revision=int(draft.revision),
            strategy_request_id=int(request.strategy_request_id),
            candidate_id=int(candidate.candidate_id),
            candidate_fingerprint=candidate.source_fingerprint,
            schema_version=DEFINITION_SCHEMA_VERSION,
            definition_version=next_definition_version,
        )
        self._session.add(definition)
        self._session.flush()
        definition.definition_hash = _definition_hash(definition)
        self._session.flush()

        provenance_fingerprint: str | None = None
        try:
            from stock_platform.ai.candidate_lifecycle.service import (
                AICandidateLifecycleService,
            )

            provenance = AICandidateLifecycleService(self._session).get_provenance(
                int(candidate.candidate_id)
            )
            provenance_fingerprint = provenance.get("combined_source_fingerprint")
        except Exception:  # noqa: BLE001 — provenance는 참고용
            pass

        approval = StrategyDraftApprovalEntity(
            draft_id=int(draft.draft_id),
            strategy_request_id=int(request.strategy_request_id),
            candidate_id=int(candidate.candidate_id),
            strategy_definition_id=int(definition.strategy_id),
            generation_run_id=(
                int(generation_run.generation_run_id) if generation_run else None
            ),
            generation_attempt_id=(
                int(attempt.generation_attempt_id) if attempt else None
            ),
            status="APPROVED",
            idempotency_key=key,
            draft_version=int(draft.version),
            draft_revision=int(draft.revision),
            candidate_fingerprint_at_approval=candidate.source_fingerprint,
            candidate_provenance_fingerprint=provenance_fingerprint,
            prompt_version_id=(
                int(generation_run.prompt_version_id)
                if generation_run and generation_run.prompt_version_id
                else None
            ),
            provider=draft.llm_provider,
            model=draft.llm_model,
            draft_content_hash=_draft_content_hash(draft),
            definition_hash=definition.definition_hash,
            schema_version=DEFINITION_SCHEMA_VERSION,
            reason=clean_reason,
            decided_by=actor,
            decided_at=_utcnow(),
        )
        self._session.add(approval)
        try:
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            raise StrategyDraftApprovalError(
                "ALREADY_APPROVED", "이미 승인된 Draft입니다(동시 승인 감지)."
            ) from exc

        # STEP12-4: Definition -> Approval 역방향 링크를 채운다(STEP12-3에서
        # 컬럼만 추가하고 실제로 채우지 않았던 결함 — Snapshot Export의
        # provenance.approval_id가 항상 None이 되는 것을 계기로 발견).
        definition.approval_id = int(approval.approval_id)
        self._session.flush()

        self._record_history(
            approval,
            action="APPROVED",
            previous_status="PENDING",
            new_status="APPROVED",
            reason=clean_reason,
            actor=actor,
            strategy_definition_id=int(definition.strategy_id),
            correlation_id=correlation_id,
        )
        self._session.commit()
        self._session.refresh(approval)
        return {**_approval_to_dict(approval), "idempotent_replay": False}

    # ------------------------------------------------------------------
    # 반려
    # ------------------------------------------------------------------
    def reject(
        self,
        draft_id: int,
        *,
        actor: str,
        reason: str,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        clean_reason = _require_reason(reason)
        key = (idempotency_key or "").strip() or uuid.uuid4().hex

        replay = self._session.scalar(
            select(StrategyDraftApprovalEntity).where(
                StrategyDraftApprovalEntity.draft_id == int(draft_id),
                StrategyDraftApprovalEntity.idempotency_key == key,
            )
        )
        if replay is not None:
            return {**_approval_to_dict(replay), "idempotent_replay": True}

        preview = self._session.get(StrategyDraftEntity, int(draft_id))
        if preview is None:
            raise StrategyDraftApprovalError("NOT_FOUND", f"Strategy Draft not found: {draft_id}")

        request = self._session.scalar(
            select(StrategyRequestEntity)
            .where(StrategyRequestEntity.strategy_request_id == preview.strategy_request_id)
            .with_for_update()
        )
        if request is None:
            raise StrategyDraftApprovalError(
                "STRATEGY_REQUEST_NOT_FOUND",
                f"Strategy Request not found: {preview.strategy_request_id}",
            )
        candidate = self._session.scalar(
            select(AICandidateLifecycleEntity)
            .where(AICandidateLifecycleEntity.candidate_id == int(request.candidate_id))
            .with_for_update()
        )
        if candidate is None:
            raise StrategyDraftApprovalError(
                "CANDIDATE_NOT_FOUND", f"Candidate not found: {request.candidate_id}"
            )

        draft = self._session.scalar(
            select(StrategyDraftEntity)
            .where(StrategyDraftEntity.draft_id == int(draft_id))
            .with_for_update()
        )
        if draft is None:
            raise StrategyDraftApprovalError("NOT_FOUND", f"Strategy Draft not found: {draft_id}")
        if draft.status != "DRAFT":
            raise StrategyDraftApprovalError(
                "DRAFT_STATUS_NOT_APPROVABLE",
                f"DRAFT 상태의 Draft만 반려할 수 있습니다. 현재: {draft.status}",
            )

        existing_active = self._session.scalar(
            select(StrategyDraftApprovalEntity)
            .where(
                StrategyDraftApprovalEntity.draft_id == int(draft_id),
                StrategyDraftApprovalEntity.status == "APPROVED",
            )
            .with_for_update()
        )
        if existing_active is not None:
            raise StrategyDraftApprovalError(
                "ALREADY_APPROVED", "이미 승인된 Draft는 반려할 수 없습니다."
            )

        approval = StrategyDraftApprovalEntity(
            draft_id=int(draft.draft_id),
            strategy_request_id=int(request.strategy_request_id),
            candidate_id=int(candidate.candidate_id),
            strategy_definition_id=None,
            status="REJECTED",
            idempotency_key=key,
            draft_version=int(draft.version),
            draft_revision=int(draft.revision),
            candidate_fingerprint_at_approval=candidate.source_fingerprint,
            provider=draft.llm_provider,
            model=draft.llm_model,
            draft_content_hash=_draft_content_hash(draft),
            schema_version=DEFINITION_SCHEMA_VERSION,
            reason=clean_reason,
            decided_by=actor,
            decided_at=_utcnow(),
        )
        self._session.add(approval)
        try:
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            raise StrategyDraftApprovalError(
                "DUPLICATE_DECISION", "이미 처리된 Draft입니다(동시 반려 감지)."
            ) from exc

        self._record_history(
            approval,
            action="REJECTED",
            previous_status="PENDING",
            new_status="REJECTED",
            reason=clean_reason,
            actor=actor,
            correlation_id=correlation_id,
        )
        self._session.commit()
        self._session.refresh(approval)
        return {**_approval_to_dict(approval), "idempotent_replay": False}

    # ------------------------------------------------------------------
    # 승인 취소
    # ------------------------------------------------------------------
    def revoke(
        self,
        approval_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        clean_reason = _require_reason(reason)
        approval = self._session.scalar(
            select(StrategyDraftApprovalEntity)
            .where(StrategyDraftApprovalEntity.approval_id == int(approval_id))
            .with_for_update()
        )
        if approval is None:
            raise StrategyDraftApprovalError(
                "NOT_FOUND", f"Approval not found: {approval_id}"
            )
        if approval.status != "APPROVED":
            raise StrategyDraftApprovalError(
                "INVALID_STATE_TRANSITION",
                f"APPROVED 상태만 취소할 수 있습니다. 현재: {approval.status}",
            )

        definition = None
        if approval.strategy_definition_id is not None:
            definition = self._session.scalar(
                select(StrategyDefinitionEntity)
                .where(
                    StrategyDefinitionEntity.strategy_id
                    == int(approval.strategy_definition_id)
                )
                .with_for_update()
            )

        previous_status = approval.status
        approval.status = "REVOKED"
        approval.revoked_reason = clean_reason
        approval.revoked_by = actor
        approval.revoked_at = _utcnow()
        if definition is not None:
            # Hard delete 금지 — 비활성화만 한다(§9). Backtest/Runtime 대상
            # 제외는 is_active=False로 표현하며, 이번 STEP은 실제 Runtime
            # 중지 작업을 수행하지 않는다.
            definition.is_active = False
            definition.updated_by = actor
        self._session.flush()

        self._record_history(
            approval,
            action="REVOKED",
            previous_status=previous_status,
            new_status="REVOKED",
            reason=clean_reason,
            actor=actor,
            strategy_definition_id=approval.strategy_definition_id,
            correlation_id=correlation_id,
        )
        self._session.commit()
        self._session.refresh(approval)
        return _approval_to_dict(approval)

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------
    def _supersede(
        self,
        approval: StrategyDraftApprovalEntity,
        *,
        actor: str,
        correlation_id: str | None,
    ) -> None:
        previous_status = approval.status
        approval.status = "SUPERSEDED"
        self._session.flush()
        if approval.strategy_definition_id is not None:
            definition = self._session.scalar(
                select(StrategyDefinitionEntity)
                .where(
                    StrategyDefinitionEntity.strategy_id
                    == int(approval.strategy_definition_id)
                )
                .with_for_update()
            )
            if definition is not None:
                definition.is_active = False
                definition.updated_by = actor
                self._session.flush()
        self._record_history(
            approval,
            action="SUPERSEDED",
            previous_status=previous_status,
            new_status="SUPERSEDED",
            reason="같은 Strategy Request의 새 Draft가 승인되어 대체됨",
            actor=actor,
            strategy_definition_id=approval.strategy_definition_id,
            correlation_id=correlation_id,
        )

    def _record_history(
        self,
        approval: StrategyDraftApprovalEntity,
        *,
        action: str,
        previous_status: str | None,
        new_status: str | None,
        actor: str,
        correlation_id: str | None,
        reason: str | None = None,
        strategy_definition_id: int | None = None,
    ) -> None:
        history = StrategyDraftApprovalHistoryEntity(
            approval_id=int(approval.approval_id),
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            reason=(reason or "").strip()[:REASON_MAX_LENGTH] or None,
            actor=actor,
            draft_version=approval.draft_version,
            draft_revision=approval.draft_revision,
            strategy_definition_id=strategy_definition_id,
            metadata_hash=approval.draft_content_hash,
            correlation_id=correlation_id,
        )
        self._session.add(history)
        self._session.flush()

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    def get(self, approval_id: int) -> dict[str, Any]:
        return _approval_to_dict(self._require(approval_id))

    def get_for_draft(self, draft_id: int) -> dict[str, Any] | None:
        row = self._session.scalar(
            select(StrategyDraftApprovalEntity)
            .where(StrategyDraftApprovalEntity.draft_id == int(draft_id))
            .order_by(StrategyDraftApprovalEntity.approval_id.desc())
            .limit(1)
        )
        return _approval_to_dict(row) if row is not None else None

    def list(
        self,
        *,
        draft_id: int | None = None,
        strategy_request_id: int | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        stmt = select(StrategyDraftApprovalEntity)
        if draft_id is not None:
            stmt = stmt.where(StrategyDraftApprovalEntity.draft_id == int(draft_id))
        if strategy_request_id is not None:
            stmt = stmt.where(
                StrategyDraftApprovalEntity.strategy_request_id == int(strategy_request_id)
            )
        if status is not None:
            stmt = stmt.where(StrategyDraftApprovalEntity.status == status)
        rows = list(
            self._session.scalars(
                stmt.order_by(StrategyDraftApprovalEntity.approval_id.desc())
                .offset(max(0, offset))
                .limit(min(max(limit, 1), 200))
            )
        )
        return {"items": [_approval_to_dict(r) for r in rows]}

    def get_history(
        self, approval_id: int, *, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        self._require(approval_id)
        rows = list(
            self._session.scalars(
                select(StrategyDraftApprovalHistoryEntity)
                .where(StrategyDraftApprovalHistoryEntity.approval_id == int(approval_id))
                .order_by(StrategyDraftApprovalHistoryEntity.history_id.desc())
                .offset(max(0, offset))
                .limit(min(max(limit, 1), 200))
            )
        )
        return {"items": [_history_to_dict(r) for r in rows]}

    def _require(self, approval_id: int) -> StrategyDraftApprovalEntity:
        row = self._session.get(StrategyDraftApprovalEntity, int(approval_id))
        if row is None:
            raise StrategyDraftApprovalError("NOT_FOUND", f"Approval not found: {approval_id}")
        return row

    # ------------------------------------------------------------------
    # STEP12-4 — Strategy Snapshot(승인으로 생성된 불변 Definition 조회)
    #
    # 새 Snapshot 테이블은 만들지 않는다 — trading.strategy_definition
    # 자체가 승인 후 불변이므로(STEP12-3) 이미 Snapshot이다. 여기서는
    # 조회/해시 무결성 검증/이력(승인 이력 재사용)/Export만 제공한다.
    # ------------------------------------------------------------------
    def _require_definition(self, strategy_definition_id: int) -> StrategyDefinitionEntity:
        row = self._session.get(StrategyDefinitionEntity, int(strategy_definition_id))
        if row is None:
            raise StrategyDraftApprovalError(
                "NOT_FOUND", f"Strategy Definition not found: {strategy_definition_id}"
            )
        return row

    def get_snapshot(self, strategy_definition_id: int) -> dict[str, Any]:
        """Snapshot 조회 + Validation(저장된 해시와 현재 내용 재계산 해시 비교)."""
        definition = self._require_definition(strategy_definition_id)
        recomputed = _definition_hash(definition)
        return {
            "strategy_definition_id": int(definition.strategy_id),
            "strategy_code": definition.strategy_code,
            "name": definition.name,
            "description": definition.description,
            "market_type": definition.market_type,
            "owner_type": definition.owner_type,
            "user_id": definition.user_id,
            "visibility": definition.visibility,
            "is_active": bool(definition.is_active),
            "parameter_payload": definition.parameter_payload or {},
            "source_draft_id": definition.source_draft_id,
            "source_draft_version": definition.source_draft_version,
            "source_draft_revision": definition.source_draft_revision,
            "strategy_request_id": definition.strategy_request_id,
            "candidate_id": definition.candidate_id,
            "candidate_fingerprint": definition.candidate_fingerprint,
            "approval_id": definition.approval_id,
            "schema_version": definition.schema_version,
            "definition_version": definition.definition_version,
            "definition_hash": definition.definition_hash,
            "hash_valid": recomputed == definition.definition_hash,
            "approved_by": definition.approved_by,
            "approved_at": definition.approved_at,
            "created_at": definition.created_at,
        }

    def get_snapshot_history(self, strategy_definition_id: int) -> dict[str, Any]:
        """Snapshot History — 새 테이블 없이 기존 Approval History를
        strategy_definition_id로 필터링해 재사용한다(그 Definition을
        만들거나 취소·대체한 결정들이 곧 이 Snapshot의 이력이다)."""
        self._require_definition(strategy_definition_id)
        rows = list(
            self._session.scalars(
                select(StrategyDraftApprovalHistoryEntity)
                .where(
                    StrategyDraftApprovalHistoryEntity.strategy_definition_id
                    == int(strategy_definition_id)
                )
                .order_by(StrategyDraftApprovalHistoryEntity.history_id.asc())
            )
        )
        return {"items": [_history_to_dict(r) for r in rows]}

    def export_snapshot(self, strategy_definition_id: int) -> dict[str, Any]:
        """Snapshot Export — Backtest 등 외부 소비자가 참조할 수 있는
        안정적 형태의 읽기 전용 번들. Import(반대 방향, 외부 JSON을 받아
        Definition을 생성/수정하는 경로)는 의도적으로 제공하지 않는다 —
        Definition은 오직 Draft 승인 경로로만 생성된다(§9 비범위 원칙과
        동일한 이유: 승인 파이프라인을 우회하는 생성 경로를 두지 않음)."""
        snapshot = self.get_snapshot(strategy_definition_id)
        if not snapshot["hash_valid"]:
            raise StrategyDraftApprovalError(
                "SNAPSHOT_HASH_MISMATCH",
                "저장된 definition_hash가 현재 내용과 일치하지 않습니다.",
            )
        return {
            "schema_version": snapshot["schema_version"],
            "definition_version": snapshot["definition_version"],
            "definition_hash": snapshot["definition_hash"],
            "strategy_code": snapshot["strategy_code"],
            "name": snapshot["name"],
            "description": snapshot["description"],
            "market_type": snapshot["market_type"],
            "parameter_payload": snapshot["parameter_payload"],
            "provenance": {
                "source_draft_id": snapshot["source_draft_id"],
                "source_draft_version": snapshot["source_draft_version"],
                "source_draft_revision": snapshot["source_draft_revision"],
                "strategy_request_id": snapshot["strategy_request_id"],
                "candidate_id": snapshot["candidate_id"],
                "candidate_fingerprint": snapshot["candidate_fingerprint"],
                "approval_id": snapshot["approval_id"],
            },
        }


def _safe_json(raw: str | None) -> Any:
    if raw is None or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
