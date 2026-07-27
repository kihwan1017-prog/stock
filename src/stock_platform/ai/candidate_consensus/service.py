"""STEP 11-10 — Multi-AI Consensus Service (create ≠ calculate ≠ synthesize)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_consensus.calculation import (
    AIConsensusCalculationService,
    strip_forbidden_fields,
)
from stock_platform.ai.candidate_consensus.constants import (
    CALCULATION_MODES,
    CONSENSUS_ENGINE_VERSION,
    CONSENSUS_TYPES,
    DETERMINISTIC_VERSION,
    MIN_MEMBERS,
    REFERENCE_DISCLAIMER,
    REVIEW_QUALITY_LABEL,
)
from stock_platform.ai.candidate_consensus.eligibility import (
    AIConsensusEligibilityService,
)
from stock_platform.ai.candidate_consensus.entities import (
    AICandidateConsensusConflictEntity,
    AICandidateConsensusEntity,
    AICandidateConsensusFactorEntity,
    AICandidateConsensusHistoryEntity,
    AICandidateConsensusMemberEntity,
)
from stock_platform.ai.candidate_consensus.independence import (
    AIConsensusIndependenceService,
)
from stock_platform.ai.candidate_consensus.weight import AIConsensusWeightService
from stock_platform.ai.execution.runner import AIExecutionRunner
from stock_platform.ai.execution.service import AIExecutionError, AIExecutionService
from stock_platform.ai.prompt.entities import (
    AIOutputSchemaEntity,
    AIPolicyDefinitionEntity,
    AIPromptTemplateEntity,
    AIPromptTemplateVersionEntity,
)
from stock_platform.ai.providers.security import sanitize_for_log


class AIConsensusError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _consensus_key(
    *,
    result_hashes: list[str],
    calculation_mode: str,
    synthesis_provider: str | None = None,
) -> str:
    sorted_hashes = sorted(h for h in result_hashes if h)
    raw = (
        f"{':'.join(sorted_hashes)}:{DETERMINISTIC_VERSION}:"
        f"{calculation_mode}:{synthesis_provider or 'none'}:"
        f"{CONSENSUS_ENGINE_VERSION}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _provider_diversity(family_count: int, member_count: int) -> str:
    if member_count <= 1:
        return "LIMITED"
    ratio = family_count / member_count
    if ratio >= 0.8:
        return "HIGH"
    if ratio >= 0.5:
        return "MODERATE"
    if ratio >= 0.3:
        return "LOW"
    return "LIMITED"


class AIConsensusService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._eligibility = AIConsensusEligibilityService(session)
        self._independence = AIConsensusIndependenceService()
        self._weight = AIConsensusWeightService(session)
        self._calc = AIConsensusCalculationService()
        self._exec = AIExecutionService(session)

    def _history(
        self,
        consensus_id: int,
        *,
        action: str,
        actor: str,
        previous: str | None = None,
        new: str | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            AICandidateConsensusHistoryEntity(
                candidate_consensus_id=consensus_id,
                action=action,
                previous_status=previous,
                new_status=new,
                reason=reason,
                requested_by=actor,
                correlation_id=correlation_id,
                detail_sanitized=sanitize_for_log(detail or {}),
            )
        )

    def _public(self, row: AICandidateConsensusEntity) -> dict[str, Any]:
        return {
            "id": row.consensus_id,
            "consensus_key": row.consensus_key,
            "consensus_type": row.consensus_type,
            "market_type": row.market_type,
            "exchange_code": row.exchange_code,
            "symbol": row.symbol,
            "instrument_id": row.instrument_id,
            "task_type": row.task_type,
            "calculation_mode": row.calculation_mode,
            "consensus_status": row.consensus_status,
            "execution_mode": row.execution_mode,
            "evidence_bundle_hash": row.evidence_bundle_hash,
            "assessment_count": row.assessment_count,
            "included_count": row.included_count,
            "excluded_count": row.excluded_count,
            "provider_count": row.provider_count,
            "provider_family_count": row.provider_family_count,
            "analytical_score": row.weighted_analytical_score,
            "risk_score": row.weighted_risk_score,
            "confidence": row.weighted_confidence,
            "agreement_level": row.agreement_level,
            "disagreement_level": row.disagreement_level,
            "evidence_consistency": row.evidence_consistency,
            "provider_diversity": row.provider_diversity,
            "execution_request_id": row.execution_request_id,
            "synthesis_provider_code": row.synthesis_provider_code,
            "synthesis_model": row.synthesis_model,
            "deterministic_version": row.deterministic_version,
            "result_hash": row.result_hash,
            "safe_result": row.safe_result,
            "warnings": row.warnings,
            "calculated_at": (
                row.calculated_at.isoformat() if row.calculated_at else None
            ),
            "synthesized_at": (
                row.synthesized_at.isoformat() if row.synthesized_at else None
            ),
            "superseded_at": (
                row.superseded_at.isoformat() if row.superseded_at else None
            ),
            "superseded_by_id": row.superseded_by_id,
            "lock_version": row.lock_version,
            "created_by": row.created_by,
            "reason": row.reason,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "disclaimer": REFERENCE_DISCLAIMER,
            "review_quality_label": REVIEW_QUALITY_LABEL,
            "external_ai_called": row.execution_mode == "EXTERNAL"
            and row.synthesized_at is not None,
        }

    def _resolve_synthesis_config(
        self,
        *,
        consensus_type: str,
        prompt_version_id: int | None,
    ) -> dict[str, Any]:
        if consensus_type == "STOCK":
            task_type = "STOCK_CANDIDATE_CONSENSUS"
            schema_code = "STOCK_CANDIDATE_CONSENSUS_RESULT_V1"
            prompt_code = "STOCK_CANDIDATE_CONSENSUS_BASE"
        else:
            task_type = "CRYPTO_CANDIDATE_CONSENSUS"
            schema_code = "CRYPTO_CANDIDATE_CONSENSUS_RESULT_V1"
            prompt_code = "CRYPTO_CANDIDATE_CONSENSUS_BASE"

        schema = self._session.scalar(
            select(AIOutputSchemaEntity).where(
                AIOutputSchemaEntity.code == schema_code,
                AIOutputSchemaEntity.status == "ACTIVE",
            )
        )
        prompt_tpl = self._session.scalar(
            select(AIPromptTemplateEntity).where(
                AIPromptTemplateEntity.code == prompt_code
            )
        )
        prompt_version = None
        if prompt_version_id:
            prompt_version = self._session.get(
                AIPromptTemplateVersionEntity, prompt_version_id
            )
        elif prompt_tpl and prompt_tpl.active_version_id:
            prompt_version = self._session.get(
                AIPromptTemplateVersionEntity, prompt_tpl.active_version_id
            )

        core_policy = self._session.scalar(
            select(AIPolicyDefinitionEntity).where(
                AIPolicyDefinitionEntity.code == "CORE_FINANCIAL_GUARDRAIL",
                AIPolicyDefinitionEntity.status == "ACTIVE",
            )
        )

        blockers: list[str] = []
        if schema is None:
            blockers.append("SCHEMA_INACTIVE_OR_MISSING")
        if prompt_tpl is None:
            blockers.append("PROMPT_TEMPLATE_MISSING")
        elif prompt_tpl.status != "ACTIVE":
            blockers.append("PROMPT_DRAFT_OR_INACTIVE")
        if prompt_version is None:
            blockers.append("PROMPT_VERSION_MISSING")
        elif prompt_version.status != "ACTIVE":
            blockers.append("PROMPT_VERSION_INACTIVE")
        if core_policy is None:
            blockers.append("CORE_POLICY_INACTIVE")

        return {
            "eligible": len(blockers) == 0,
            "blockers": blockers,
            "task_type": task_type,
            "schema_id": schema.output_schema_id if schema else None,
            "prompt_template_id": (
                prompt_tpl.prompt_template_id if prompt_tpl else None
            ),
            "prompt_version_id": (
                prompt_version.prompt_template_version_id
                if prompt_version
                else None
            ),
            "policy_ids": (
                [core_policy.policy_definition_id] if core_policy else []
            ),
        }

    def _store_member_rows(
        self,
        consensus_id: int,
        selection: dict[str, Any],
        weighted: list[dict[str, Any]] | None = None,
    ) -> None:
        weighted_by_id = {
            m.get("assessment_id"): m for m in (weighted or [])
        }
        for item in selection.get("included") or []:
            aid = item["assessment_id"]
            w = weighted_by_id.get(aid, {})
            self._session.add(
                AICandidateConsensusMemberEntity(
                    candidate_consensus_id=consensus_id,
                    candidate_assessment_id=aid,
                    included=True,
                    provider_code=item.get("provider_code"),
                    model=item.get("model"),
                    provider_family=w.get("provider_family"),
                    independence_status=w.get("independence_status"),
                    base_weight=w.get("base_weight"),
                    review_weight=w.get("review_weight"),
                    scorecard_weight=w.get("scorecard_weight"),
                    calibration_weight=w.get("calibration_weight"),
                    citation_weight=w.get("citation_weight"),
                    data_quality_weight=w.get("data_quality_weight"),
                    independence_weight=w.get("independence_weight"),
                    final_weight=w.get("final_weight"),
                    analytical_score=item.get("analytical_score"),
                    risk_score=item.get("risk_score"),
                    confidence=item.get("confidence"),
                    review_decision=item.get("review_decision"),
                    evidence_bundle_hash=item.get("evidence_bundle_hash"),
                    result_hash=item.get("result_hash"),
                )
            )

        for ex in selection.get("excluded") or []:
            self._session.add(
                AICandidateConsensusMemberEntity(
                    candidate_consensus_id=consensus_id,
                    candidate_assessment_id=ex.get("id"),
                    included=False,
                    exclusion_reason=str(ex.get("reason") or "")[:500],
                )
            )

    def create(
        self,
        *,
        actor: str,
        reason: str,
        assessment_ids: list[int],
        calculation_mode: str = "DETERMINISTIC_ONLY",
        execution_mode: str = "MOCK",
        require_reviewed_members: bool = False,
        synthesis_provider_code: str | None = None,
        idempotency_key: str,
        force_new_version: bool = False,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if calculation_mode not in CALCULATION_MODES:
            raise AIConsensusError("INVALID_MODE", f"bad mode {calculation_mode}")

        existing = self._session.scalar(
            select(AICandidateConsensusEntity).where(
                AICandidateConsensusEntity.created_by == actor,
                AICandidateConsensusEntity.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return {
                "idempotent_replay": True,
                "consensus": self._public(existing),
            }

        selection = self._eligibility.select_members(
            assessment_ids,
            require_reviewed_members=require_reviewed_members,
        )
        if not selection.get("eligible"):
            raise AIConsensusError(
                "NOT_ELIGIBLE",
                ",".join(selection.get("warnings") or ["ineligible"]),
            )

        instrument = selection.get("instrument") or {}
        consensus_type = str(
            instrument.get("assessment_type")
            or instrument.get("market_type")
            or "STOCK"
        )
        if consensus_type not in CONSENSUS_TYPES:
            raise AIConsensusError("INVALID_TYPE", f"type {consensus_type}")

        task_type = (
            "STOCK_CANDIDATE_CONSENSUS"
            if consensus_type == "STOCK"
            else "CRYPTO_CANDIDATE_CONSENSUS"
        )

        included = selection["included"]
        result_hashes = [str(m.get("result_hash") or "") for m in included]
        synth_provider = (
            (synthesis_provider_code or "none").lower()
            if calculation_mode == "DETERMINISTIC_PLUS_SYNTHESIS"
            else None
        )
        key = _consensus_key(
            result_hashes=result_hashes,
            calculation_mode=calculation_mode,
            synthesis_provider=synth_provider,
        )

        same = self._session.scalar(
            select(AICandidateConsensusEntity).where(
                AICandidateConsensusEntity.consensus_key == key,
                AICandidateConsensusEntity.consensus_status.notin_(
                    ["SUPERSEDED", "CANCELLED", "FAILED", "ARCHIVED"]
                ),
            )
        )
        if same is not None and not force_new_version:
            return {
                "idempotent_replay": True,
                "consensus": self._public(same),
                "code": "DUPLICATE_CONSENSUS",
            }

        providers = {
            (m.get("provider_code") or "").lower() for m in included
        }
        families = {
            AIConsensusIndependenceService().classify([m])[0].get(
                "provider_family"
            )
            for m in included
        }
        models = {(m.get("model") or "") for m in included}

        corr = correlation_id or uuid.uuid4().hex[:32]
        row = AICandidateConsensusEntity(
            consensus_key=key
            if not force_new_version
            else f"{key}:{uuid.uuid4().hex[:8]}",
            idempotency_key=idempotency_key,
            consensus_type=consensus_type,
            market_type=str(instrument.get("market_type") or consensus_type),
            exchange_code=str(instrument.get("exchange_code") or ""),
            symbol=str(instrument.get("symbol") or ""),
            instrument_id=instrument.get("instrument_id"),
            task_type=task_type,
            calculation_mode=calculation_mode,
            consensus_status="DRAFT",
            execution_mode=execution_mode,
            evidence_bundle_hash=selection.get("evidence_bundle_hash"),
            assessment_count=len(assessment_ids),
            included_count=len(included),
            excluded_count=len(selection.get("excluded") or []),
            provider_count=len({p for p in providers if p}),
            provider_family_count=len({f for f in families if f}),
            model_count=len({m for m in models if m}),
            deterministic_version=DETERMINISTIC_VERSION,
            synthesis_provider_code=synthesis_provider_code,
            warnings=list(selection.get("warnings") or []),
            created_by=actor,
            reason=reason[:500],
            correlation_id=corr,
        )
        self._session.add(row)
        self._session.flush()

        self._store_member_rows(row.consensus_id, selection)

        self._history(
            row.consensus_id,
            action="AI_CONSENSUS_CREATED",
            actor=actor,
            new="DRAFT",
            reason=reason,
            correlation_id=corr,
            detail={
                "included": len(included),
                "excluded": len(selection.get("excluded") or []),
            },
        )
        self._session.commit()
        self._session.refresh(row)
        return {
            "idempotent_replay": False,
            "consensus": self._public(row),
            "selection": {
                "included_count": len(included),
                "excluded_count": len(selection.get("excluded") or []),
                "warnings": selection.get("warnings"),
            },
        }

    def dry_run(self, consensus_id: int, *, actor: str) -> dict[str, Any]:
        row = self._session.get(AICandidateConsensusEntity, consensus_id)
        if row is None:
            raise AIConsensusError("NOT_FOUND", "consensus not found")

        member_payloads = self._load_included_member_payloads(consensus_id)
        assessment_ids = [m["assessment_id"] for m in member_payloads]
        selection = self._eligibility.select_members(assessment_ids)
        classified = self._independence.classify(selection.get("included") or [])
        weighted = self._weight.compute_weights(classified)

        self._history(
            consensus_id,
            action="AI_CONSENSUS_DRY_RUN",
            actor=actor,
            previous=row.consensus_status,
            correlation_id=row.correlation_id,
            detail={"member_count": len(weighted)},
        )
        self._session.commit()

        preview = self._calc.calculate(weighted)
        return {
            "ok": True,
            "consensus": self._public(row),
            "eligibility": selection,
            "weights_preview": [
                {
                    "assessment_id": m.get("assessment_id"),
                    "final_weight": m.get("final_weight"),
                    "normalized_weight": m.get("normalized_weight"),
                    "independence_status": m.get("independence_status"),
                }
                for m in weighted
            ],
            "calculation_preview": preview if preview.get("ok") else None,
            "external_ai_called": False,
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def _load_included_member_payloads(
        self, consensus_id: int
    ) -> list[dict[str, Any]]:
        rows = self._session.scalars(
            select(AICandidateConsensusMemberEntity).where(
                AICandidateConsensusMemberEntity.candidate_consensus_id
                == consensus_id,
                AICandidateConsensusMemberEntity.included.is_(True),
            )
        ).all()
        ids = [r.candidate_assessment_id for r in rows if r.candidate_assessment_id]
        selection = self._eligibility.select_members(ids)
        return selection.get("included") or []

    def calculate(
        self,
        consensus_id: int,
        *,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        row = self._session.get(AICandidateConsensusEntity, consensus_id)
        if row is None:
            raise AIConsensusError("NOT_FOUND", "consensus not found")
        if row.consensus_status in {
            "CANCELLED",
            "SUPERSEDED",
            "ARCHIVED",
            "BLOCKED",
        }:
            raise AIConsensusError(
                "INVALID_STATUS", f"status {row.consensus_status}"
            )

        prev = row.consensus_status
        member_payloads = self._load_included_member_payloads(consensus_id)
        if len(member_payloads) < MIN_MEMBERS:
            raise AIConsensusError(
                "INSUFFICIENT_MEMBERS",
                f"need at least {MIN_MEMBERS} included members",
            )

        classified = self._independence.classify(member_payloads)
        weighted = self._weight.compute_weights(classified)
        outcome = self._calc.calculate(weighted)
        if not outcome.get("ok"):
            row.consensus_status = "FAILED"
            self._history(
                consensus_id,
                action="AI_CONSENSUS_CALC_FAILED",
                actor=actor,
                previous=prev,
                new="FAILED",
                reason=str(outcome.get("code")),
                correlation_id=row.correlation_id,
            )
            self._session.commit()
            raise AIConsensusError(
                str(outcome.get("code") or "CALC_FAILED"),
                ",".join(outcome.get("warnings") or ["calc failed"]),
            )

        self._session.execute(
            delete(AICandidateConsensusFactorEntity).where(
                AICandidateConsensusFactorEntity.candidate_consensus_id
                == consensus_id
            )
        )
        self._session.execute(
            delete(AICandidateConsensusConflictEntity).where(
                AICandidateConsensusConflictEntity.candidate_consensus_id
                == consensus_id
            )
        )

        for factor in outcome.get("factors") or []:
            self._session.add(
                AICandidateConsensusFactorEntity(
                    candidate_consensus_id=consensus_id,
                    factor_type=str(factor.get("factor_type") or "NEUTRAL"),
                    factor_code=str(factor.get("factor_code") or "FACTOR")[:80],
                    direction=str(factor.get("direction") or "NEUTRAL")[:20],
                    agreement_count=int(factor.get("support_count") or 0),
                    disagreement_count=int(factor.get("oppose_count") or 0),
                    weighted_support=factor.get("weighted_support"),
                    evidence_summary=str(factor.get("evidence_summary") or "")[
                        :1000
                    ],
                )
            )

        for conflict in outcome.get("conflicts") or []:
            self._session.add(
                AICandidateConsensusConflictEntity(
                    candidate_consensus_id=consensus_id,
                    conflict_type=str(
                        conflict.get("conflict_code")
                        or conflict.get("conflict_type")
                        or "CONFLICT"
                    )[:60],
                    severity=str(conflict.get("severity") or "MEDIUM")[:20],
                    field_path=str(conflict.get("field_path") or "")[:200] or None,
                    description_sanitized=str(
                        conflict.get("description") or ""
                    )[:2000],
                    assessment_ids=conflict.get("member_assessment_ids"),
                    resolution_status=str(
                        conflict.get("resolution_status") or "UNRESOLVED"
                    ),
                )
            )

        member_entities = self._session.scalars(
            select(AICandidateConsensusMemberEntity).where(
                AICandidateConsensusMemberEntity.candidate_consensus_id
                == consensus_id,
                AICandidateConsensusMemberEntity.included.is_(True),
            )
        ).all()
        weighted_by_id = {
            m.get("assessment_id"): m for m in weighted
        }
        for ent in member_entities:
            w = weighted_by_id.get(ent.candidate_assessment_id, {})
            ent.provider_family = w.get("provider_family")
            ent.independence_status = w.get("independence_status")
            ent.base_weight = w.get("base_weight")
            ent.review_weight = w.get("review_weight")
            ent.scorecard_weight = w.get("scorecard_weight")
            ent.calibration_weight = w.get("calibration_weight")
            ent.citation_weight = w.get("citation_weight")
            ent.data_quality_weight = w.get("data_quality_weight")
            ent.independence_weight = w.get("independence_weight")
            ent.final_weight = w.get("final_weight")

        families = {m.get("provider_family") for m in weighted}
        new_status = str(outcome.get("consensus_status") or "CALCULATED")
        row.consensus_status = new_status
        row.weighted_analytical_score = outcome.get("analytical_score")
        row.weighted_risk_score = outcome.get("risk_score")
        row.weighted_confidence = outcome.get("confidence")
        row.agreement_level = outcome.get("agreement_level")
        row.disagreement_level = outcome.get("disagreement_level")
        row.provider_diversity = _provider_diversity(
            len({f for f in families if f}), len(weighted)
        )
        row.evidence_consistency = (
            "HIGH"
            if outcome.get("agreement_level") == "STRONG_AGREEMENT"
            else "MIXED"
        )
        row.safe_result = sanitize_for_log(outcome.get("safe_result"))
        row.result_hash = outcome.get("result_hash")
        row.warnings = list(
            set((row.warnings or []) + (outcome.get("warnings") or []))
        )
        row.calculated_at = _now()
        row.lock_version = int(row.lock_version) + 1

        self._history(
            consensus_id,
            action="AI_CONSENSUS_CALCULATED",
            actor=actor,
            previous=prev,
            new=new_status,
            reason=reason,
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        self._session.refresh(row)
        return {
            "consensus": self._public(row),
            "external_ai_called": False,
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    async def synthesize(
        self,
        consensus_id: int,
        *,
        actor: str,
        reason: str,
        confirm: bool = False,
        execution_mode: str | None = None,
        provider_code: str | None = None,
        model: str | None = None,
        prompt_version_id: int | None = None,
        max_tokens: int = 1024,
        timeout_sec: float = 60.0,
    ) -> dict[str, Any]:
        row = self._session.get(AICandidateConsensusEntity, consensus_id)
        if row is None:
            raise AIConsensusError("NOT_FOUND", "consensus not found")
        if row.calculation_mode != "DETERMINISTIC_PLUS_SYNTHESIS":
            raise AIConsensusError(
                "MODE_NOT_SYNTHESIS",
                "calculation_mode must be DETERMINISTIC_PLUS_SYNTHESIS",
            )
        if row.consensus_status not in {
            "CALCULATED",
            "VALIDATED",
            "VALIDATED_WITH_WARNINGS",
        }:
            raise AIConsensusError(
                "NOT_CALCULATED",
                f"status {row.consensus_status} — calculate first",
            )

        exec_mode = execution_mode or row.execution_mode or "MOCK"
        if exec_mode == "EXTERNAL" and not confirm:
            raise AIConsensusError(
                "CONFIRM_REQUIRED", "external synthesis requires confirm=true"
            )

        det_snapshot = {
            "analytical_score": row.weighted_analytical_score,
            "risk_score": row.weighted_risk_score,
            "confidence": row.weighted_confidence,
            "agreement_level": row.agreement_level,
            "disagreement_level": row.disagreement_level,
        }

        prompt_cfg = self._resolve_synthesis_config(
            consensus_type=row.consensus_type,
            prompt_version_id=prompt_version_id,
        )
        if not prompt_cfg["eligible"]:
            raise AIConsensusError(
                "NOT_ELIGIBLE",
                ",".join(prompt_cfg.get("blockers") or ["prompt_blocked"]),
            )

        provider = (provider_code or row.synthesis_provider_code or "mock").lower()
        model_name = model or row.synthesis_model or (
            "mock-v1" if provider == "mock" else "default"
        )
        members = self.members(consensus_id)
        input_payload = {
            "symbol": row.symbol,
            "exchange_code": row.exchange_code,
            "market_type": row.market_type,
            "consensus_type": row.consensus_type,
            "deterministic_json": json.dumps(
                row.safe_result or {}, ensure_ascii=False
            )[:30_000],
            "member_summaries_json": json.dumps(
                [
                    {
                        "assessment_id": m.get("assessment_id"),
                        "provider": m.get("provider_code"),
                        "analytical_score": m.get("analytical_score"),
                        "risk_score": m.get("risk_score"),
                        "weight": m.get("final_weight"),
                    }
                    for m in members
                    if m.get("included")
                ],
                ensure_ascii=False,
            )[:20_000],
            "agreement_level": row.agreement_level or "",
            "disagreement_level": row.disagreement_level or "",
        }

        try:
            exec_result = self._exec.create_request(
                actor=actor,
                reason=reason[:500],
                task_type=str(prompt_cfg["task_type"]),
                execution_mode=exec_mode,
                idempotency_key=f"consensus-synth-{consensus_id}"[:64],
                input_payload=input_payload,
                provider_code=provider,
                requested_model=model_name,
                prompt_template_id=prompt_cfg.get("prompt_template_id"),
                prompt_version_id=prompt_cfg.get("prompt_version_id"),
                output_schema_id=prompt_cfg.get("schema_id"),
                policy_ids=prompt_cfg.get("policy_ids"),
                max_tokens=max_tokens,
                timeout_sec=timeout_sec,
                fallback_enabled=False,
                correlation_id=row.correlation_id,
            )
        except AIExecutionError as exc:
            raise AIConsensusError(exc.code, exc.message) from exc

        exec_req_id = exec_result["request"]["id"]
        row.execution_request_id = exec_req_id
        row.execution_mode = exec_mode
        row.synthesis_provider_code = provider
        row.synthesis_model = model_name
        row.prompt_template_id = prompt_cfg.get("prompt_template_id")
        row.prompt_version_id = prompt_cfg.get("prompt_version_id")
        row.output_schema_id = prompt_cfg.get("schema_id")
        row.policy_ids = prompt_cfg.get("policy_ids")
        self._session.commit()

        try:
            runner_result = await AIExecutionRunner(self._session).execute(
                exec_req_id,
                actor=actor,
                confirm=confirm,
            )
        except AIExecutionError as exc:
            self._history(
                consensus_id,
                action="AI_CONSENSUS_SYNTHESIS_FAILED",
                actor=actor,
                reason=exc.message,
                correlation_id=row.correlation_id,
            )
            self._session.commit()
            raise AIConsensusError(exc.code, exc.message) from exc

        exec_result = self._exec.get_result(exec_req_id)
        synthesis_payload: dict[str, Any] = {}
        if exec_result and exec_result.get("result_payload"):
            raw = exec_result["result_payload"]
            if isinstance(raw, dict):
                body = (
                    raw.get("result")
                    if isinstance(raw.get("result"), dict)
                    else raw
                )
                cleaned, _ = strip_forbidden_fields(
                    body if isinstance(body, dict) else {}
                )
                synthesis_payload = cleaned

        safe = dict(row.safe_result or {})
        safe["synthesis"] = sanitize_for_log(
            {
                "summary": synthesis_payload.get("reasoning_summary")
                or synthesis_payload.get("consensus_summary"),
                "narrative": synthesis_payload.get("consensus_narrative"),
                "warnings": synthesis_payload.get("warnings") or [],
                "provider_code": provider,
                "model": model_name,
                "execution_mode": exec_mode,
            }
        )
        row.safe_result = safe
        row.synthesized_at = _now()
        row.execution_result_id = exec_result.get("id") if exec_result else None

        # Meta-Synthesis — deterministic 점수 복원
        row.weighted_analytical_score = det_snapshot["analytical_score"]
        row.weighted_risk_score = det_snapshot["risk_score"]
        row.weighted_confidence = det_snapshot["confidence"]
        row.agreement_level = det_snapshot["agreement_level"]
        row.disagreement_level = det_snapshot["disagreement_level"]

        self._history(
            consensus_id,
            action="AI_CONSENSUS_SYNTHESIZED",
            actor=actor,
            detail={
                "external_ai_called": bool(runner_result.get("external_ai_called")),
                "execution_request_id": exec_req_id,
            },
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        self._session.refresh(row)
        return {
            "consensus": self._public(row),
            "execution": runner_result,
            "external_ai_called": bool(runner_result.get("external_ai_called")),
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def cancel(
        self, consensus_id: int, *, actor: str, reason: str
    ) -> dict[str, Any]:
        row = self._session.get(AICandidateConsensusEntity, consensus_id)
        if row is None:
            raise AIConsensusError("NOT_FOUND", "consensus not found")

        prev = row.consensus_status
        if row.execution_request_id:
            try:
                self._exec.cancel(
                    row.execution_request_id,
                    actor=actor,
                    reason=reason,
                )
            except AIExecutionError:
                pass

        row.consensus_status = "CANCELLED"
        self._history(
            consensus_id,
            action="AI_CONSENSUS_CANCELLED",
            actor=actor,
            previous=prev,
            new="CANCELLED",
            reason=reason,
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        return {"consensus": self._public(row)}

    def recalculate(
        self,
        consensus_id: int,
        *,
        actor: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        old = self._session.get(AICandidateConsensusEntity, consensus_id)
        if old is None:
            raise AIConsensusError("NOT_FOUND", "consensus not found")

        member_rows = self._session.scalars(
            select(AICandidateConsensusMemberEntity).where(
                AICandidateConsensusMemberEntity.candidate_consensus_id
                == consensus_id,
                AICandidateConsensusMemberEntity.included.is_(True),
            )
        ).all()
        assessment_ids = [
            r.candidate_assessment_id
            for r in member_rows
            if r.candidate_assessment_id
        ]

        created = self.create(
            actor=actor,
            reason=reason,
            assessment_ids=assessment_ids,
            calculation_mode=old.calculation_mode,
            execution_mode=old.execution_mode,
            synthesis_provider_code=old.synthesis_provider_code,
            idempotency_key=idempotency_key,
            force_new_version=True,
            correlation_id=old.correlation_id,
        )
        new_id = created["consensus"]["id"]
        calc = self.calculate(new_id, actor=actor, reason=reason)

        prev = old.consensus_status
        old.consensus_status = "SUPERSEDED"
        old.superseded_at = _now()
        old.superseded_by_id = new_id
        self._history(
            old.consensus_id,
            action="AI_CONSENSUS_SUPERSEDED",
            actor=actor,
            previous=prev,
            new="SUPERSEDED",
            reason=reason,
            detail={"superseded_by_id": new_id},
            correlation_id=old.correlation_id,
        )
        self._history(
            new_id,
            action="AI_CONSENSUS_RECALCULATED",
            actor=actor,
            detail={"previous_id": old.consensus_id},
            correlation_id=old.correlation_id,
        )
        self._session.commit()
        return calc

    async def resynthesize(
        self,
        consensus_id: int,
        *,
        actor: str,
        reason: str,
        confirm: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await self.synthesize(
            consensus_id,
            actor=actor,
            reason=reason,
            confirm=confirm,
            **kwargs,
        )

    def request_review(
        self,
        consensus_id: int,
        *,
        actor: str,
        reason: str,
        assigned_reviewer_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._session.get(AICandidateConsensusEntity, consensus_id)
        if row is None:
            raise AIConsensusError("NOT_FOUND", "consensus not found")
        if row.consensus_status not in {
            "VALIDATED",
            "VALIDATED_WITH_WARNINGS",
            "CALCULATED",
        }:
            raise AIConsensusError(
                "NOT_REVIEWABLE",
                f"status {row.consensus_status} not reviewable",
            )

        assignment: dict[str, Any] | None = None
        try:
            from stock_platform.ai.review.service import AIReviewService

            review_svc = AIReviewService(self._session)
            result = review_svc.create_assignment(
                actor=actor,
                reason=reason,
                analysis_source_type="CANDIDATE_CONSENSUS",
                source_analysis_id=consensus_id,
                assigned_reviewer_id=assigned_reviewer_id,
                idempotency_key=f"consensus-review-{consensus_id}",
            )
            assignment = result.get("assignment")
        except Exception as exc:
            self._history(
                consensus_id,
                action="AI_CONSENSUS_REVIEW_REQUESTED",
                actor=actor,
                detail={"warning": str(exc)[:200]},
                correlation_id=row.correlation_id,
            )

        prev = row.consensus_status
        row.consensus_status = "REVIEW_PENDING"
        self._history(
            consensus_id,
            action="AI_CONSENSUS_REVIEW_REQUESTED",
            actor=actor,
            previous=prev,
            new="REVIEW_PENDING",
            reason=reason,
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        self._session.refresh(row)
        return {
            "consensus": self._public(row),
            "assignment": assignment,
            "disclaimer": REVIEW_QUALITY_LABEL,
        }

    def get(self, consensus_id: int) -> dict[str, Any]:
        row = self._session.get(AICandidateConsensusEntity, consensus_id)
        if row is None:
            raise AIConsensusError("NOT_FOUND", "consensus not found")
        return self._public(row)

    def list(
        self,
        *,
        consensus_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        stmt = select(AICandidateConsensusEntity).order_by(
            AICandidateConsensusEntity.consensus_id.desc()
        )
        if consensus_type:
            stmt = stmt.where(
                AICandidateConsensusEntity.consensus_type == consensus_type
            )
        rows = self._session.scalars(stmt.limit(min(limit, 200))).all()
        return [self._public(r) for r in rows]

    def members(self, consensus_id: int) -> list[dict[str, Any]]:
        rows = self._session.scalars(
            select(AICandidateConsensusMemberEntity)
            .where(
                AICandidateConsensusMemberEntity.candidate_consensus_id
                == consensus_id
            )
            .order_by(AICandidateConsensusMemberEntity.id)
        ).all()
        return [
            {
                "id": r.id,
                "assessment_id": r.candidate_assessment_id,
                "included": r.included,
                "exclusion_reason": r.exclusion_reason,
                "provider_code": r.provider_code,
                "model": r.model,
                "provider_family": r.provider_family,
                "independence_status": r.independence_status,
                "final_weight": r.final_weight,
                "analytical_score": r.analytical_score,
                "risk_score": r.risk_score,
                "confidence": r.confidence,
                "review_decision": r.review_decision,
            }
            for r in rows
        ]

    def weights(self, consensus_id: int) -> dict[str, Any]:
        row = self._session.get(AICandidateConsensusEntity, consensus_id)
        if row is None:
            raise AIConsensusError("NOT_FOUND", "consensus not found")
        member_payloads = self._load_included_member_payloads(consensus_id)
        classified = self._independence.classify(member_payloads)
        weighted = self._weight.compute_weights(classified)
        return {
            "consensus_id": consensus_id,
            "weights": weighted,
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def conflicts(self, consensus_id: int) -> list[dict[str, Any]]:
        rows = self._session.scalars(
            select(AICandidateConsensusConflictEntity).where(
                AICandidateConsensusConflictEntity.candidate_consensus_id
                == consensus_id
            )
        ).all()
        return [
            {
                "id": r.id,
                "conflict_type": r.conflict_type,
                "severity": r.severity,
                "field_path": r.field_path,
                "description": r.description_sanitized,
                "assessment_ids": r.assessment_ids,
                "resolution_status": r.resolution_status,
            }
            for r in rows
        ]

    def history(self, consensus_id: int) -> list[dict[str, Any]]:
        rows = self._session.scalars(
            select(AICandidateConsensusHistoryEntity)
            .where(
                AICandidateConsensusHistoryEntity.candidate_consensus_id
                == consensus_id
            )
            .order_by(AICandidateConsensusHistoryEntity.id.desc())
            .limit(100)
        ).all()
        return [
            {
                "id": r.id,
                "action": r.action,
                "previous_status": r.previous_status,
                "new_status": r.new_status,
                "reason": r.reason,
                "requested_by": r.requested_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    def compare(self, left_id: int, right_id: int) -> dict[str, Any]:
        left = self.get(left_id)
        right = self.get(right_id)
        return {
            "left": left,
            "right": right,
            "diff": {
                "evidence_bundle_hash": [
                    left.get("evidence_bundle_hash"),
                    right.get("evidence_bundle_hash"),
                ],
                "analytical_score": [
                    left.get("analytical_score"),
                    right.get("analytical_score"),
                ],
                "agreement_level": [
                    left.get("agreement_level"),
                    right.get("agreement_level"),
                ],
                "included_count": [
                    left.get("included_count"),
                    right.get("included_count"),
                ],
                "result_equal": left.get("safe_result") == right.get("safe_result"),
            },
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def dashboard_summary(self) -> dict[str, Any]:
        rows = self._session.scalars(
            select(AICandidateConsensusEntity).limit(500)
        ).all()
        today = _now().date()

        def _today(r: AICandidateConsensusEntity) -> bool:
            return bool(r.calculated_at and r.calculated_at.date() == today) or bool(
                r.created_at and r.created_at.date() == today
            )

        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r.consensus_status] = by_status.get(r.consensus_status, 0) + 1

        confs = [
            float(r.weighted_confidence)
            for r in rows
            if r.weighted_confidence is not None
        ]
        split_count = sum(
            1
            for r in rows
            if r.agreement_level in {"SPLIT", "WEAK_AGREEMENT"}
        )

        return {
            "consensus_today": sum(1 for r in rows if _today(r)),
            "stock_consensus": sum(1 for r in rows if r.consensus_type == "STOCK"),
            "crypto_consensus": sum(1 for r in rows if r.consensus_type == "CRYPTO"),
            "calculated": by_status.get("CALCULATED", 0)
            + by_status.get("VALIDATED", 0)
            + by_status.get("VALIDATED_WITH_WARNINGS", 0),
            "review_pending": by_status.get("REVIEW_PENDING", 0),
            "split_or_weak": split_count,
            "superseded": by_status.get("SUPERSEDED", 0),
            "average_confidence": (
                round(sum(confs) / len(confs), 4) if confs else None
            ),
            "disclaimer": REFERENCE_DISCLAIMER,
            "external_ai_called": False,
        }
