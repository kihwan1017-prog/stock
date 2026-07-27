"""STEP 11-9 — Candidate Assessment Service (create ≠ execute, Candidate 테이블 미연결)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_assessment.constants import (
    ASSESSMENT_ENGINE_VERSION,
    REFERENCE_DISCLAIMER,
    REVIEW_QUALITY_LABEL,
)
from stock_platform.ai.candidate_assessment.eligibility import (
    AICandidateEligibilityService,
)
from stock_platform.ai.candidate_assessment.entities import (
    AICandidateAssessmentEntity,
    AICandidateAssessmentEvidenceEntity,
    AICandidateAssessmentFactorEntity,
    AICandidateAssessmentHistoryEntity,
    AICandidateAssessmentRiskEntity,
)
from stock_platform.ai.candidate_assessment.evidence import AICandidateEvidenceService
from stock_platform.ai.candidate_assessment.scoring import (
    apply_confidence_caps,
    clamp_score,
    compute_analytical_score,
    strip_forbidden_fields,
    validate_result_payload,
)
from stock_platform.ai.execution.runner import AIExecutionRunner
from stock_platform.ai.execution.service import AIExecutionError, AIExecutionService
from stock_platform.ai.prompt.entities import (
    AIOutputSchemaEntity,
    AIPolicyDefinitionEntity,
    AIPromptTemplateEntity,
    AIPromptTemplateVersionEntity,
)
from stock_platform.ai.providers.security import sanitize_for_log


class AICandidateAssessmentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _assessment_key(
    *,
    assessment_type: str,
    instrument_key: str,
    evidence_bundle_hash: str,
    prompt_version_id: int | None,
    schema_id: int | None,
    provider: str,
    model: str,
) -> str:
    prefix = "stock-assessment" if assessment_type == "STOCK" else "crypto-assessment"
    raw = (
        f"{prefix}:{instrument_key}:{evidence_bundle_hash}:"
        f"p{prompt_version_id or 0}:s{schema_id or 0}:"
        f"{provider}:{model}:{ASSESSMENT_ENGINE_VERSION}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


class AICandidateAssessmentService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._eligibility = AICandidateEligibilityService(session)
        self._evidence = AICandidateEvidenceService(session)
        self._exec = AIExecutionService(session)

    def _history(
        self,
        assessment_id: int,
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
            AICandidateAssessmentHistoryEntity(
                candidate_assessment_id=assessment_id,
                action=action,
                previous_status=previous,
                new_status=new,
                reason=reason,
                requested_by=actor,
                correlation_id=correlation_id,
                detail_sanitized=sanitize_for_log(detail or {}),
            )
        )

    def _resolve_prompt_config(
        self,
        *,
        assessment_type: str,
        prompt_version_id: int | None,
    ) -> dict[str, Any]:
        if assessment_type == "STOCK":
            task_type = "STOCK_CANDIDATE_ANALYSIS"
            schema_code = "STOCK_CANDIDATE_ASSESSMENT_RESULT_V1"
            prompt_code = "STOCK_CANDIDATE_ASSESSMENT_BASE"
        else:
            task_type = "CRYPTO_CANDIDATE_ANALYSIS"
            schema_code = "CRYPTO_CANDIDATE_ASSESSMENT_RESULT_V1"
            prompt_code = "CRYPTO_CANDIDATE_ASSESSMENT_BASE"

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

    def _public(self, row: AICandidateAssessmentEntity) -> dict[str, Any]:
        return {
            "id": row.assessment_id,
            "assessment_key": row.assessment_key,
            "assessment_type": row.assessment_type,
            "market_type": row.market_type,
            "exchange_code": row.exchange_code,
            "symbol": row.symbol,
            "instrument_id": row.instrument_id,
            "task_type": row.task_type,
            "assessment_status": row.assessment_status,
            "execution_mode": row.execution_mode,
            "data_classification": row.data_classification,
            "execution_request_id": row.execution_request_id,
            "provider_code": row.provider_code,
            "model": row.model,
            "evidence_bundle_hash": row.evidence_bundle_hash,
            "analytical_score": row.analytical_score,
            "risk_score": row.risk_score,
            "overall_score": row.overall_score,
            "confidence": row.confidence,
            "evidence_quality": row.evidence_quality,
            "data_quality": row.data_quality,
            "conflict_status": row.conflict_status,
            "temporal_alignment_status": row.temporal_alignment_status,
            "review_decision": row.review_decision,
            "warnings": row.warnings,
            "safe_result": row.safe_result,
            "assessed_at": row.assessed_at.isoformat() if row.assessed_at else None,
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
        }

    def _store_evidence_rows(
        self,
        assessment_id: int,
        items: list[dict[str, Any]],
    ) -> None:
        for idx, item in enumerate(items):
            analyzed_raw = item.get("analyzed_at")
            analyzed_at = None
            if analyzed_raw:
                try:
                    analyzed_at = datetime.fromisoformat(
                        str(analyzed_raw).replace("Z", "+00:00")
                    )
                except ValueError:
                    analyzed_at = None

            self._session.add(
                AICandidateAssessmentEvidenceEntity(
                    candidate_assessment_id=assessment_id,
                    evidence_type=str(item.get("evidence_type") or "OTHER"),
                    source_analysis_type=str(
                        item.get("source_analysis_type") or "OTHER"
                    ),
                    document_analysis_id=item.get("document_analysis_id"),
                    market_analysis_id=item.get("market_analysis_id"),
                    review_decision_id=item.get("review_decision_id"),
                    source_version=item.get("source_version"),
                    evidence_hash=item.get("evidence_hash"),
                    quality_status=item.get("quality_status"),
                    direction=item.get("direction"),
                    temporal_status=item.get("temporal_status"),
                    summary_sanitized=str(item.get("summary") or "")[:2000],
                    included=bool(item.get("included", True)),
                    exclusion_reason=item.get("exclusion_reason"),
                    analyzed_at=analyzed_at,
                    sort_order=idx,
                )
            )

    def create(
        self,
        *,
        actor: str,
        reason: str,
        market_type: str,
        exchange_code: str,
        symbol: str,
        instrument_id: int | None = None,
        execution_mode: str = "MOCK",
        provider_code: str | None = None,
        model: str | None = None,
        prompt_version_id: int | None = None,
        max_tokens: int = 768,
        timeout_sec: float = 45.0,
        fallback_enabled: bool = False,
        include_news: bool = True,
        include_disclosure: bool = True,
        include_chart: bool = True,
        include_market: bool = True,
        require_reviewed_evidence: bool = False,
        idempotency_key: str,
        force_new_version: bool = False,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        existing = self._session.scalar(
            select(AICandidateAssessmentEntity).where(
                AICandidateAssessmentEntity.created_by == actor,
                AICandidateAssessmentEntity.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return {
                "idempotent_replay": True,
                "assessment": self._public(existing),
            }

        elig = self._eligibility.validate(
            market_type=market_type,
            exchange_code=exchange_code,
            symbol=symbol,
            instrument_id=instrument_id,
        )
        if not elig["allowed"]:
            raise AICandidateAssessmentError(
                "NOT_ELIGIBLE",
                ",".join(elig.get("reasons") or ["blocked"]),
            )

        bundle = self._evidence.build_bundle(
            self._session,
            market_type=market_type,
            exchange=elig["exchange_code"],
            symbol=elig["symbol"],
            include_news=include_news,
            include_disclosure=include_disclosure,
            include_chart=include_chart,
            include_market=include_market,
            require_reviewed_evidence=require_reviewed_evidence,
        )
        if not bundle.get("ok"):
            raise AICandidateAssessmentError(
                str(bundle.get("code") or "EVIDENCE_FAILED"),
                str(bundle.get("message") or "evidence bundle failed"),
            )

        assessment_type = str(elig.get("assessment_type") or market_type)
        prompt_cfg = self._resolve_prompt_config(
            assessment_type=assessment_type,
            prompt_version_id=prompt_version_id,
        )
        if not prompt_cfg["eligible"]:
            raise AICandidateAssessmentError(
                "NOT_ELIGIBLE",
                ",".join(prompt_cfg.get("blockers") or ["prompt_blocked"]),
            )

        provider = (provider_code or "mock").lower()
        model_name = model or ("mock-v1" if provider == "mock" else "default")
        instrument_key = str(
            elig.get("instrument_id")
            or elig.get("instrument_key")
            or f"{elig['exchange_code']}:{elig['symbol']}"
        )

        key = _assessment_key(
            assessment_type=assessment_type,
            instrument_key=instrument_key,
            evidence_bundle_hash=str(bundle["hash"]),
            prompt_version_id=prompt_cfg.get("prompt_version_id"),
            schema_id=prompt_cfg.get("schema_id"),
            provider=provider,
            model=model_name,
        )

        same = self._session.scalar(
            select(AICandidateAssessmentEntity).where(
                AICandidateAssessmentEntity.assessment_key == key,
                AICandidateAssessmentEntity.assessment_status.notin_(
                    ["SUPERSEDED", "CANCELLED", "FAILED", "ARCHIVED"]
                ),
            )
        )
        if same is not None and not force_new_version:
            return {
                "idempotent_replay": True,
                "assessment": self._public(same),
                "code": "DUPLICATE_ASSESSMENT",
            }

        input_payload = {
            "market_type": market_type,
            "exchange_code": elig["exchange_code"],
            "symbol": elig["symbol"],
            "instrument_id": str(instrument_id or instrument_key),
            "evidence_bundle_hash": bundle["hash"],
            "evidence_count": str(bundle["counts"].get("included", 0)),
            "evidence_quality": str(bundle.get("evidence_quality") or ""),
            "data_quality": str(bundle.get("data_quality") or ""),
            "conflict_status": str(bundle.get("conflict_status") or ""),
            "temporal_status": str(bundle.get("temporal_status") or ""),
            "evidence_json": json.dumps(
                [
                    i.get("safe_result_summary") or {"summary": i.get("summary")}
                    for i in bundle["items"]
                    if i.get("included")
                ],
                ensure_ascii=False,
            )[:40_000],
        }

        try:
            exec_result = self._exec.create_request(
                actor=actor,
                reason=reason[:500],
                task_type=str(prompt_cfg["task_type"]),
                execution_mode=execution_mode,
                idempotency_key=f"cand-{idempotency_key}"[:64],
                input_payload=input_payload,
                provider_code=provider,
                requested_model=model_name,
                prompt_template_id=prompt_cfg.get("prompt_template_id"),
                prompt_version_id=prompt_cfg.get("prompt_version_id"),
                output_schema_id=prompt_cfg.get("schema_id"),
                policy_ids=prompt_cfg.get("policy_ids"),
                max_tokens=max_tokens,
                timeout_sec=timeout_sec,
                fallback_enabled=fallback_enabled,
                correlation_id=correlation_id or uuid.uuid4().hex[:32],
            )
        except AIExecutionError as exc:
            raise AICandidateAssessmentError(exc.code, exc.message) from exc

        exec_req = exec_result["request"]
        source_version_hash = hashlib.sha256(
            json.dumps(
                [
                    {
                        "t": i.get("evidence_type"),
                        "id": i.get("source_analysis_id"),
                        "v": i.get("source_version"),
                    }
                    for i in bundle["items"]
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()[:64]

        row = AICandidateAssessmentEntity(
            assessment_key=key if not force_new_version else f"{key}:{uuid.uuid4().hex[:8]}",
            idempotency_key=idempotency_key,
            assessment_type=assessment_type,
            market_type=market_type,
            exchange_code=elig["exchange_code"],
            symbol=elig["symbol"],
            instrument_id=instrument_id,
            instrument_key=instrument_key,
            task_type=str(prompt_cfg["task_type"]),
            assessment_status="DRAFT",
            execution_mode=execution_mode,
            data_classification="PUBLIC_DERIVED",
            execution_request_id=exec_req["id"],
            prompt_template_id=prompt_cfg.get("prompt_template_id"),
            prompt_version_id=prompt_cfg.get("prompt_version_id"),
            output_schema_id=prompt_cfg.get("schema_id"),
            policy_ids=prompt_cfg.get("policy_ids"),
            provider_code=provider,
            model=model_name,
            evidence_bundle_hash=bundle["hash"],
            source_version_hash=source_version_hash,
            input_hash=hashlib.sha256(
                json.dumps(input_payload, sort_keys=True).encode()
            ).hexdigest(),
            evidence_quality=str(bundle.get("evidence_quality")),
            data_quality=str(bundle.get("data_quality")),
            conflict_status=str(bundle.get("conflict_status")),
            temporal_alignment_status=str(bundle.get("temporal_status")),
            warnings=list(elig.get("warnings") or []),
            created_by=actor,
            reason=reason[:500],
            correlation_id=correlation_id or exec_req.get("correlation_id"),
        )
        self._session.add(row)
        self._session.flush()

        self._store_evidence_rows(row.assessment_id, list(bundle["items"]))

        self._history(
            row.assessment_id,
            action="AI_CANDIDATE_ASSESSMENT_CREATED",
            actor=actor,
            new="DRAFT",
            reason=reason,
            correlation_id=row.correlation_id,
            detail={
                "evidence_bundle_hash": row.evidence_bundle_hash,
                "execution_request_id": row.execution_request_id,
                "counts": bundle.get("counts"),
            },
        )
        self._history(
            row.assessment_id,
            action="AI_CANDIDATE_EVIDENCE_SELECTED",
            actor=actor,
            detail={
                "included": bundle["counts"].get("included"),
                "excluded": bundle["counts"].get("excluded"),
            },
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        self._session.refresh(row)
        return {
            "idempotent_replay": False,
            "assessment": self._public(row),
            "eligibility_warnings": elig.get("warnings"),
            "evidence_summary": {
                "hash": bundle["hash"],
                "counts": bundle["counts"],
                "conflict_status": bundle.get("conflict_status"),
                "temporal_status": bundle.get("temporal_status"),
            },
        }

    def dry_run(self, assessment_id: int, *, actor: str) -> dict[str, Any]:
        row = self._session.get(AICandidateAssessmentEntity, assessment_id)
        if row is None:
            raise AICandidateAssessmentError("NOT_FOUND", "assessment not found")
        if row.execution_request_id is None:
            raise AICandidateAssessmentError("NO_EXECUTION", "missing execution")

        self._history(
            assessment_id,
            action="AI_CANDIDATE_DRY_RUN_STARTED",
            actor=actor,
            previous=row.assessment_status,
            correlation_id=row.correlation_id,
        )
        result = AIExecutionRunner(self._session).dry_run(
            row.execution_request_id, actor=actor
        )
        evidence_rows = self._session.scalars(
            select(AICandidateAssessmentEvidenceEntity).where(
                AICandidateAssessmentEvidenceEntity.candidate_assessment_id
                == assessment_id
            )
        ).all()
        self._history(
            assessment_id,
            action="AI_CANDIDATE_DRY_RUN_COMPLETED",
            actor=actor,
            detail={"ok": result.get("ok"), "external_ai_called": False},
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        return {
            **result,
            "assessment": self._public(row),
            "disclaimer": REFERENCE_DISCLAIMER,
            "external_ai_called": False,
            "evidence_summary": {
                "hash": row.evidence_bundle_hash,
                "included": sum(1 for e in evidence_rows if e.included),
                "excluded": sum(1 for e in evidence_rows if not e.included),
                "conflict_status": row.conflict_status,
                "temporal_status": row.temporal_alignment_status,
            },
        }

    async def execute(
        self,
        assessment_id: int,
        *,
        actor: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        row = self._session.get(AICandidateAssessmentEntity, assessment_id)
        if row is None:
            raise AICandidateAssessmentError("NOT_FOUND", "assessment not found")
        if row.execution_request_id is None:
            raise AICandidateAssessmentError("NO_EXECUTION", "missing execution")
        if row.data_quality == "INVALID":
            row.assessment_status = "BLOCKED"
            self._history(
                assessment_id,
                action="AI_CANDIDATE_DATA_POLICY_BLOCKED",
                actor=actor,
                previous=row.assessment_status,
                new="BLOCKED",
                correlation_id=row.correlation_id,
            )
            self._session.commit()
            raise AICandidateAssessmentError("DATA_QUALITY_INVALID", "quality INVALID")

        self._history(
            assessment_id,
            action="AI_CANDIDATE_EXECUTION_REQUESTED",
            actor=actor,
            previous=row.assessment_status,
            new="RUNNING",
            detail={"confirm": confirm, "mode": row.execution_mode},
            correlation_id=row.correlation_id,
        )
        row.assessment_status = "RUNNING"
        self._session.commit()

        try:
            result = await AIExecutionRunner(self._session).execute(
                row.execution_request_id,
                actor=actor,
                confirm=confirm,
            )
        except AIExecutionError as exc:
            row.assessment_status = "FAILED"
            self._history(
                assessment_id,
                action="AI_CANDIDATE_FAILED",
                actor=actor,
                previous="RUNNING",
                new="FAILED",
                reason=exc.message,
                correlation_id=row.correlation_id,
            )
            self._session.commit()
            raise AICandidateAssessmentError(exc.code, exc.message) from exc

        exec_req = self._exec.get_request(row.execution_request_id)
        exec_result = self._exec.get_result(row.execution_request_id)
        self._apply_outcome(
            row,
            actor=actor,
            exec_req=exec_req,
            exec_result=exec_result,
            runner_ok=bool(result.get("ok")),
        )
        self._session.commit()
        self._session.refresh(row)
        return {
            "ok": bool(result.get("ok")),
            "assessment": self._public(row),
            "execution": result,
            "disclaimer": REFERENCE_DISCLAIMER,
            "external_ai_called": bool(result.get("external_ai_called")),
            "mock_called": bool(result.get("mock_called")),
        }

    def _apply_outcome(
        self,
        row: AICandidateAssessmentEntity,
        *,
        actor: str,
        exec_req: dict[str, Any],
        exec_result: dict[str, Any] | None,
        runner_ok: bool,
    ) -> None:
        status = str(exec_req.get("status") or "")
        prev = row.assessment_status

        if status in {"SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"} and exec_result:
            payload = exec_result.get("result_payload") or {}
            cleaned, violations = strip_forbidden_fields(
                payload if isinstance(payload, dict) else {}
            )
            findings = validate_result_payload(cleaned, row.task_type)
            warnings = list(exec_result.get("warnings") or [])
            warnings.extend([f"FORBIDDEN:{v}" for v in violations])
            warnings.extend(findings)

            result_body = (
                cleaned.get("result") if isinstance(cleaned.get("result"), dict) else cleaned
            ) or {}

            sub_scores = {
                "news_score": result_body.get("news_assessment", {}).get("score")
                if isinstance(result_body.get("news_assessment"), dict)
                else result_body.get("news_score"),
                "disclosure_score": result_body.get("disclosure_assessment", {}).get(
                    "score"
                )
                if isinstance(result_body.get("disclosure_assessment"), dict)
                else result_body.get("disclosure_score"),
                "chart_score": result_body.get("chart_assessment", {}).get("score")
                if isinstance(result_body.get("chart_assessment"), dict)
                else result_body.get("chart_score"),
                "market_score": result_body.get("market_assessment", {}).get("score")
                if isinstance(result_body.get("market_assessment"), dict)
                else result_body.get("market_score"),
                "evidence_quality_score": result_body.get("evidence_quality_score"),
                "uncertainty_score": result_body.get("uncertainty_score"),
                "analytical_score": result_body.get("analytical_score"),
            }

            analytical = compute_analytical_score(sub_scores)
            risk_raw = result_body.get("risk_score")
            risk_score = clamp_score(risk_raw if risk_raw is not None else 50)

            has_review = any(
                e.included and e.review_decision_id
                for e in self._session.scalars(
                    select(AICandidateAssessmentEvidenceEntity).where(
                        AICandidateAssessmentEvidenceEntity.candidate_assessment_id
                        == row.assessment_id,
                        AICandidateAssessmentEvidenceEntity.included.is_(True),
                    )
                ).all()
            )
            metadata_only = str(row.evidence_quality or "").upper() in {
                "LOW",
                "INSUFFICIENT",
            }
            confidence = apply_confidence_caps(
                exec_result.get("confidence") or result_body.get("confidence"),
                has_review=has_review,
                conflict_status=row.conflict_status,
                temporal_status=row.temporal_alignment_status,
                metadata_only=metadata_only,
            )

            for factor_list, factor_type in (
                (result_body.get("positive_factors") or [], "POSITIVE"),
                (result_body.get("negative_factors") or [], "NEGATIVE"),
                (result_body.get("neutral_factors") or [], "NEUTRAL"),
            ):
                for idx, factor in enumerate(list(factor_list)[:20]):
                    if isinstance(factor, dict):
                        code = str(factor.get("code") or factor.get("name") or idx)[
                            :80
                        ]
                        summary = str(
                            factor.get("summary") or factor.get("description") or ""
                        )[:1000]
                        direction = str(
                            factor.get("direction") or factor_type
                        ).upper()
                    else:
                        code = str(factor)[:80]
                        summary = str(factor)[:1000]
                        direction = factor_type
                    self._session.add(
                        AICandidateAssessmentFactorEntity(
                            candidate_assessment_id=row.assessment_id,
                            factor_type=factor_type,
                            factor_code=code,
                            direction=direction
                            if direction in {"POSITIVE", "NEGATIVE", "NEUTRAL", "UNCERTAIN"}
                            else "UNCERTAIN",
                            evidence_summary=summary,
                            citation_reference=None,
                        )
                    )

            for risk in list(result_body.get("risk_factors") or [])[:20]:
                if isinstance(risk, dict):
                    risk_type = str(risk.get("type") or risk.get("code") or "RISK")[
                        :40
                    ]
                    severity = str(risk.get("severity") or "MEDIUM")[:20]
                    summary = str(
                        risk.get("summary") or risk.get("description") or ""
                    )[:1000]
                else:
                    risk_type = "RISK"
                    severity = "MEDIUM"
                    summary = str(risk)[:1000]
                self._session.add(
                    AICandidateAssessmentRiskEntity(
                        candidate_assessment_id=row.assessment_id,
                        risk_type=risk_type,
                        severity=severity,
                        evidence_summary=summary,
                    )
                )

            if row.conflict_status == "MAJOR_CONFLICT":
                self._history(
                    row.assessment_id,
                    action="AI_CANDIDATE_MAJOR_CONFLICT",
                    actor=actor,
                    detail={"conflict_status": row.conflict_status},
                    correlation_id=row.correlation_id,
                )

            new_status = (
                "VALIDATED_WITH_WARNINGS"
                if status == "SUCCEEDED_WITH_WARNINGS" or warnings
                else "VALIDATED"
            )
            row.safe_result = sanitize_for_log(cleaned)
            row.result_hash = exec_result.get("result_hash")
            row.analytical_score = analytical
            row.risk_score = risk_score
            row.overall_score = analytical
            row.confidence = confidence
            row.warnings = warnings
            row.assessment_status = new_status
            row.assessed_at = _now()
            row.lock_version = int(row.lock_version) + 1

            self._history(
                row.assessment_id,
                action="AI_CANDIDATE_VALIDATED"
                if new_status == "VALIDATED"
                else "AI_CANDIDATE_WARNING",
                actor=actor,
                previous=prev,
                new=new_status,
                correlation_id=row.correlation_id,
            )
            self._history(
                row.assessment_id,
                action="AI_CANDIDATE_COMPLETED",
                actor=actor,
                previous=prev,
                new=new_status,
                correlation_id=row.correlation_id,
            )
            self._supersede_previous_on_success(
                row.assessment_id, actor=actor, reason=row.reason
            )
        elif status == "BLOCKED":
            row.assessment_status = "BLOCKED"
            self._history(
                row.assessment_id,
                action="AI_CANDIDATE_BLOCKED",
                actor=actor,
                previous=prev,
                new="BLOCKED",
                correlation_id=row.correlation_id,
            )
        elif status == "CANCELLED":
            row.assessment_status = "CANCELLED"
            self._history(
                row.assessment_id,
                action="AI_CANDIDATE_CANCELLED",
                actor=actor,
                previous=prev,
                new="CANCELLED",
                correlation_id=row.correlation_id,
            )
        else:
            row.assessment_status = "FAILED" if not runner_ok else "INVALID"
            self._history(
                row.assessment_id,
                action="AI_CANDIDATE_FAILED",
                actor=actor,
                previous=prev,
                new=row.assessment_status,
                correlation_id=row.correlation_id,
            )

    def cancel(
        self, assessment_id: int, *, actor: str, reason: str
    ) -> dict[str, Any]:
        row = self._session.get(AICandidateAssessmentEntity, assessment_id)
        if row is None:
            raise AICandidateAssessmentError("NOT_FOUND", "assessment not found")

        self._history(
            assessment_id,
            action="AI_CANDIDATE_CANCEL_REQUESTED",
            actor=actor,
            previous=row.assessment_status,
            reason=reason,
            correlation_id=row.correlation_id,
        )
        if row.execution_request_id:
            try:
                self._exec.cancel(
                    row.execution_request_id, actor=actor, reason=reason
                )
            except AIExecutionError as exc:
                raise AICandidateAssessmentError(exc.code, exc.message) from exc
        row.assessment_status = "CANCELLED"
        self._history(
            assessment_id,
            action="AI_CANDIDATE_CANCELLED",
            actor=actor,
            new="CANCELLED",
            reason=reason,
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        return {"assessment": self._public(row)}

    def reassess(
        self,
        assessment_id: int,
        *,
        actor: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        old = self._session.get(AICandidateAssessmentEntity, assessment_id)
        if old is None:
            raise AICandidateAssessmentError("NOT_FOUND", "assessment not found")

        created = self.create(
            actor=actor,
            reason=reason,
            market_type=old.market_type,
            exchange_code=old.exchange_code,
            symbol=old.symbol,
            instrument_id=old.instrument_id,
            execution_mode=old.execution_mode,
            provider_code=old.provider_code,
            model=old.model,
            prompt_version_id=old.prompt_version_id,
            idempotency_key=idempotency_key,
            force_new_version=True,
            correlation_id=old.correlation_id,
        )
        new_id = created["assessment"]["id"]
        if new_id != old.assessment_id:
            # execute 성공 후 _supersede_previous_on_success 에서 SUPERSEDED 처리
            self._history(
                new_id,
                action="AI_CANDIDATE_REASSESSMENT_CREATED",
                actor=actor,
                reason=reason,
                detail={"previous_id": old.assessment_id},
                correlation_id=old.correlation_id,
            )
            self._session.commit()
        return created

    def _supersede_previous_on_success(
        self,
        assessment_id: int,
        *,
        actor: str,
        reason: str | None = None,
    ) -> None:
        """재평가 성공 시 이전 Assessment SUPERSEDED — execute 완료 후만 호출."""

        hist = self._session.scalar(
            select(AICandidateAssessmentHistoryEntity)
            .where(
                AICandidateAssessmentHistoryEntity.candidate_assessment_id
                == assessment_id,
                AICandidateAssessmentHistoryEntity.action
                == "AI_CANDIDATE_REASSESSMENT_CREATED",
            )
            .order_by(AICandidateAssessmentHistoryEntity.id.desc())
            .limit(1)
        )
        if hist is None or not hist.detail_sanitized:
            return
        previous_id = hist.detail_sanitized.get("previous_id")
        if not previous_id:
            return
        old = self._session.get(AICandidateAssessmentEntity, int(previous_id))
        if old is None or old.assessment_status == "SUPERSEDED":
            return
        prev = old.assessment_status
        old.assessment_status = "SUPERSEDED"
        old.superseded_at = _now()
        old.superseded_by_id = assessment_id
        self._history(
            old.assessment_id,
            action="AI_CANDIDATE_SUPERSEDED",
            actor=actor,
            previous=prev,
            new="SUPERSEDED",
            reason=reason,
            detail={"superseded_by_id": assessment_id},
            correlation_id=old.correlation_id,
        )

    def request_review(
        self,
        assessment_id: int,
        *,
        actor: str,
        reason: str,
        assigned_reviewer_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._session.get(AICandidateAssessmentEntity, assessment_id)
        if row is None:
            raise AICandidateAssessmentError("NOT_FOUND", "assessment not found")
        if row.assessment_status not in {
            "VALIDATED",
            "VALIDATED_WITH_WARNINGS",
        }:
            raise AICandidateAssessmentError(
                "NOT_REVIEWABLE",
                f"status {row.assessment_status} not reviewable",
            )

        assignment: dict[str, Any] | None = None
        try:
            from stock_platform.ai.review.service import AIReviewService

            review_svc = AIReviewService(self._session)
            result = review_svc.create_assignment(
                actor=actor,
                reason=reason,
                analysis_source_type="CANDIDATE_ASSESSMENT",
                source_analysis_id=assessment_id,
                assigned_reviewer_id=assigned_reviewer_id,
                idempotency_key=f"cand-review-{assessment_id}",
            )
            assignment = result.get("assignment")
        except Exception as exc:
            # Review 서비스 미연동 시에도 REVIEW_PENDING 상태 전환
            self._history(
                assessment_id,
                action="AI_CANDIDATE_REVIEW_REQUESTED",
                actor=actor,
                detail={"warning": str(exc)[:200]},
                correlation_id=row.correlation_id,
            )

        prev = row.assessment_status
        row.assessment_status = "REVIEW_PENDING"
        self._history(
            assessment_id,
            action="AI_CANDIDATE_REVIEW_REQUESTED",
            actor=actor,
            previous=prev,
            new="REVIEW_PENDING",
            reason=reason,
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        self._session.refresh(row)
        return {
            "assessment": self._public(row),
            "assignment": assignment,
            "disclaimer": REVIEW_QUALITY_LABEL,
        }

    def get(self, assessment_id: int) -> dict[str, Any]:
        row = self._session.get(AICandidateAssessmentEntity, assessment_id)
        if row is None:
            raise AICandidateAssessmentError("NOT_FOUND", "assessment not found")
        return self._public(row)

    def get_evidence(self, assessment_id: int) -> list[dict[str, Any]]:
        row = self._session.get(AICandidateAssessmentEntity, assessment_id)
        if row is None:
            raise AICandidateAssessmentError("NOT_FOUND", "assessment not found")
        rows = self._session.scalars(
            select(AICandidateAssessmentEvidenceEntity)
            .where(
                AICandidateAssessmentEvidenceEntity.candidate_assessment_id
                == assessment_id
            )
            .order_by(AICandidateAssessmentEvidenceEntity.sort_order)
        ).all()
        return [
            {
                "id": r.id,
                "evidence_type": r.evidence_type,
                "source_analysis_type": r.source_analysis_type,
                "document_analysis_id": r.document_analysis_id,
                "market_analysis_id": r.market_analysis_id,
                "review_decision_id": r.review_decision_id,
                "quality_status": r.quality_status,
                "direction": r.direction,
                "temporal_status": r.temporal_status,
                "summary": r.summary_sanitized,
                "included": r.included,
                "exclusion_reason": r.exclusion_reason,
                "analyzed_at": r.analyzed_at.isoformat() if r.analyzed_at else None,
            }
            for r in rows
        ]

    def get_history(self, assessment_id: int) -> list[dict[str, Any]]:
        rows = self._session.scalars(
            select(AICandidateAssessmentHistoryEntity)
            .where(
                AICandidateAssessmentHistoryEntity.candidate_assessment_id
                == assessment_id
            )
            .order_by(AICandidateAssessmentHistoryEntity.id.desc())
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

    def list(
        self,
        *,
        market_type: str | None = None,
        assessment_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        stmt = select(AICandidateAssessmentEntity).order_by(
            AICandidateAssessmentEntity.assessment_id.desc()
        )
        if market_type:
            stmt = stmt.where(
                AICandidateAssessmentEntity.market_type == market_type
            )
        if assessment_type:
            stmt = stmt.where(
                AICandidateAssessmentEntity.assessment_type == assessment_type
            )
        rows = self._session.scalars(stmt.limit(min(limit, 200))).all()
        return [self._public(r) for r in rows]

    def compare(self, left_id: int, right_id: int) -> dict[str, Any]:
        left = self.get(left_id)
        right = self.get(right_id)
        return {
            "left": left,
            "right": right,
            "diff": {
                "provider": [left.get("provider_code"), right.get("provider_code")],
                "model": [left.get("model"), right.get("model")],
                "evidence_bundle_hash": [
                    left.get("evidence_bundle_hash"),
                    right.get("evidence_bundle_hash"),
                ],
                "analytical_score": [
                    left.get("analytical_score"),
                    right.get("analytical_score"),
                ],
                "risk_score": [left.get("risk_score"), right.get("risk_score")],
                "confidence": [left.get("confidence"), right.get("confidence")],
                "conflict_status": [
                    left.get("conflict_status"),
                    right.get("conflict_status"),
                ],
                "result_equal": left.get("safe_result") == right.get("safe_result"),
            },
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def dashboard_summary(self) -> dict[str, Any]:
        rows = self._session.scalars(
            select(AICandidateAssessmentEntity).limit(500)
        ).all()
        today = _now().date()

        def _today(r: AICandidateAssessmentEntity) -> bool:
            return bool(r.assessed_at and r.assessed_at.date() == today) or bool(
                r.created_at and r.created_at.date() == today
            )

        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r.assessment_status] = by_status.get(r.assessment_status, 0) + 1

        confs = [float(r.confidence) for r in rows if r.confidence is not None]
        scores = [
            float(r.analytical_score)
            for r in rows
            if r.analytical_score is not None
        ]

        return {
            "assessments_today": sum(1 for r in rows if _today(r)),
            "stock_assessments": sum(
                1 for r in rows if r.assessment_type == "STOCK"
            ),
            "crypto_assessments": sum(
                1 for r in rows if r.assessment_type == "CRYPTO"
            ),
            "running": by_status.get("RUNNING", 0),
            "queued": by_status.get("QUEUED", 0),
            "succeeded": by_status.get("VALIDATED", 0)
            + by_status.get("VALIDATED_WITH_WARNINGS", 0),
            "failed": by_status.get("FAILED", 0),
            "blocked": by_status.get("BLOCKED", 0),
            "review_pending": by_status.get("REVIEW_PENDING", 0),
            "review_approved": by_status.get("REVIEW_APPROVED", 0),
            "major_conflict": sum(
                1 for r in rows if r.conflict_status == "MAJOR_CONFLICT"
            ),
            "low_evidence_quality": sum(
                1
                for r in rows
                if str(r.evidence_quality or "").upper() in {"LOW", "INSUFFICIENT"}
            ),
            "stale_evidence": sum(
                1
                for r in rows
                if r.temporal_alignment_status in {"STALE", "CONFLICTED"}
            ),
            "average_confidence": (
                round(sum(confs) / len(confs), 4) if confs else None
            ),
            "average_analytical_score": (
                round(sum(scores) / len(scores), 2) if scores else None
            ),
            "superseded": by_status.get("SUPERSEDED", 0),
            "mock_vs_external": {
                "mock": sum(1 for r in rows if r.execution_mode == "MOCK"),
                "external": sum(
                    1 for r in rows if r.execution_mode == "EXTERNAL"
                ),
            },
            "disclaimer": REFERENCE_DISCLAIMER,
            "external_ai_called": False,
        }
