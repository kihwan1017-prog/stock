"""STEP 11-6 — Document Analysis Service (create ≠ execute, 매매 연결 없음)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.document_analysis.constants import (
    ANALYSIS_ENGINE_VERSION,
    DOCUMENT_TYPES,
    HARD_BATCH_CAP,
    MAX_BATCH_EXTERNAL,
    MAX_BATCH_MOCK,
    REFERENCE_DISCLAIMER,
)
from stock_platform.ai.document_analysis.eligibility import (
    AIDocumentEligibilityService,
)
from stock_platform.ai.document_analysis.entities import (
    AIDocumentAnalysisCitationEntity,
    AIDocumentAnalysisDisclosureLinkEntity,
    AIDocumentAnalysisEntity,
    AIDocumentAnalysisEntityRow,
    AIDocumentAnalysisHistoryEntity,
    AIDocumentAnalysisNewsLinkEntity,
    AIDocumentAnalysisTopicEntity,
)
from stock_platform.ai.document_analysis.entity_resolver import resolve_entities
from stock_platform.ai.execution.runner import AIExecutionRunner
from stock_platform.ai.execution.service import AIExecutionError, AIExecutionService
from stock_platform.ai.providers.security import sanitize_for_log


class AIDocumentAnalysisError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_analysis_key(
    *,
    document_type: str,
    source_key: str,
    source_version: str,
    prompt_version_id: int | None,
    schema_id: int | None,
    provider: str,
    model: str,
) -> str:
    raw = (
        f"{document_type.lower()}:{source_key}:{source_version}:"
        f"p{prompt_version_id or 0}:s{schema_id or 0}:"
        f"{provider}:{model}:{ANALYSIS_ENGINE_VERSION}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


class AIDocumentAnalysisService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._eligibility = AIDocumentEligibilityService(session)
        self._exec = AIExecutionService(session)

    def _history(
        self,
        analysis_id: int,
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
            AIDocumentAnalysisHistoryEntity(
                document_analysis_id=analysis_id,
                action=action,
                previous_status=previous,
                new_status=new,
                reason=reason,
                requested_by=actor,
                correlation_id=correlation_id,
                detail_sanitized=sanitize_for_log(detail or {}),
            )
        )

    def _public(self, row: AIDocumentAnalysisEntity) -> dict[str, Any]:
        return {
            "id": row.document_analysis_id,
            "analysis_key": row.analysis_key,
            "document_type": row.document_type,
            "source_document_id": row.source_document_id,
            "source_document_key": row.source_document_key,
            "source_version": row.source_version,
            "market_type": row.market_type,
            "symbol": row.symbol,
            "company_id": row.company_id,
            "task_type": row.task_type,
            "analysis_status": row.analysis_status,
            "execution_mode": row.execution_mode,
            "data_classification": row.data_classification,
            "execution_request_id": row.execution_request_id,
            "execution_result_id": row.execution_result_id,
            "provider_code": row.provider_code,
            "model": row.model,
            "prompt_version_id": row.prompt_version_id,
            "output_schema_id": row.output_schema_id,
            "confidence": row.confidence,
            "risk_level": row.risk_level,
            "chunk_count": row.chunk_count,
            "warnings": row.warnings,
            "unresolved_entities": row.unresolved_entities,
            "unmatched_symbols": row.unmatched_symbols,
            "safe_result": row.safe_result,
            "source_missing": row.source_missing,
            "analyzed_at": row.analyzed_at.isoformat() if row.analyzed_at else None,
            "superseded_at": (
                row.superseded_at.isoformat() if row.superseded_at else None
            ),
            "superseded_by_id": row.superseded_by_id,
            "created_by": row.created_by,
            "reason": row.reason,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "disclaimer": REFERENCE_DISCLAIMER,
            # Raw Prompt / Raw Response 미포함
        }

    def create(
        self,
        *,
        actor: str,
        reason: str,
        document_type: str,
        source_document_id: int,
        execution_mode: str = "MOCK",
        provider_code: str | None = None,
        model: str | None = None,
        prompt_version_id: int | None = None,
        max_tokens: int = 512,
        timeout_sec: float = 30.0,
        fallback_enabled: bool = False,
        idempotency_key: str,
        force_new_version: bool = False,
        correlation_id: str | None = None,
        has_internal_notes: bool = False,
    ) -> dict[str, Any]:
        if document_type not in DOCUMENT_TYPES:
            raise AIDocumentAnalysisError(
                "INVALID_DOCUMENT_TYPE", "NEWS or DISCLOSURE only"
            )

        existing = self._session.scalar(
            select(AIDocumentAnalysisEntity).where(
                AIDocumentAnalysisEntity.created_by == actor,
                AIDocumentAnalysisEntity.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return {
                "idempotent_replay": True,
                "analysis": self._public(existing),
            }

        eval_result = self._eligibility.evaluate(
            document_type=document_type,
            source_document_id=source_document_id,
            execution_mode=execution_mode,
            provider_code=provider_code or "mock",
            prompt_version_id=prompt_version_id,
            has_internal_notes=has_internal_notes,
        )
        if not eval_result["eligible"]:
            raise AIDocumentAnalysisError(
                "NOT_ELIGIBLE",
                ",".join(eval_result.get("blockers") or ["blocked"]),
            )

        doc = eval_result["normalized"]
        provider = (provider_code or "mock").lower()
        model_name = model or ("mock-v1" if provider == "mock" else "default")
        analysis_key = _build_analysis_key(
            document_type=document_type,
            source_key=doc["source_document_key"],
            source_version=doc["source_version"],
            prompt_version_id=eval_result.get("prompt_version_id"),
            schema_id=eval_result.get("schema_id"),
            provider=provider,
            model=model_name,
        )

        same_key = self._session.scalar(
            select(AIDocumentAnalysisEntity).where(
                AIDocumentAnalysisEntity.analysis_key == analysis_key,
                AIDocumentAnalysisEntity.analysis_status.notin_(
                    ["SUPERSEDED", "CANCELLED", "FAILED"]
                ),
            )
        )
        if same_key is not None and not force_new_version:
            return {
                "idempotent_replay": True,
                "analysis": self._public(same_key),
                "code": "DUPLICATE_ANALYSIS",
            }

        # Execution input (prompt variables)
        if document_type == "NEWS":
            input_payload = {
                "symbol": doc.get("symbol") or "UNKNOWN",
                "news_items": doc["wrapped_body"],
                "market_type": doc.get("market_type") or "UNKNOWN",
            }
            task_type = "NEWS_ANALYSIS"
        else:
            input_payload = {
                "receipt_no": doc["receipt_no"],
                "corp_name": doc["corp_name"],
                "disclosure_body": doc["wrapped_body"],
                "stock_code": doc.get("stock_code") or "",
                "is_correction": str(bool(doc.get("is_correction"))),
            }
            task_type = "DISCLOSURE_ANALYSIS"

        try:
            exec_result = self._exec.create_request(
                actor=actor,
                reason=reason[:500],
                task_type=task_type,
                execution_mode=execution_mode,
                idempotency_key=f"doc-{idempotency_key}"[:64],
                input_payload=input_payload,
                provider_code=provider,
                requested_model=model_name,
                prompt_template_id=eval_result.get("prompt_template_id"),
                prompt_version_id=eval_result.get("prompt_version_id"),
                output_schema_id=eval_result.get("schema_id"),
                policy_ids=eval_result.get("policy_ids"),
                max_tokens=max_tokens,
                timeout_sec=timeout_sec,
                fallback_enabled=fallback_enabled,
                correlation_id=correlation_id or uuid.uuid4().hex[:32],
            )
        except AIExecutionError as exc:
            raise AIDocumentAnalysisError(exc.code, exc.message) from exc

        exec_req = exec_result["request"]
        row = AIDocumentAnalysisEntity(
            analysis_key=analysis_key
            if not force_new_version
            else f"{analysis_key}:{uuid.uuid4().hex[:8]}",
            idempotency_key=idempotency_key,
            document_type=document_type,
            source_document_id=source_document_id,
            source_document_key=doc["source_document_key"],
            source_version=doc["source_version"],
            market_type=doc.get("market_type"),
            symbol=doc.get("symbol"),
            company_id=doc.get("company_id") or doc.get("corp_code"),
            execution_request_id=exec_req["id"],
            task_type=task_type,
            analysis_status="DRAFT_ANALYSIS",
            execution_mode=execution_mode,
            data_classification=eval_result["document"]["data_classification"],
            prompt_template_id=eval_result.get("prompt_template_id"),
            prompt_version_id=eval_result.get("prompt_version_id"),
            output_schema_id=eval_result.get("schema_id"),
            policy_ids=eval_result.get("policy_ids"),
            provider_code=provider,
            model=model_name,
            content_hash=doc.get("content_hash"),
            normalized_content_hash=doc.get("normalized_content_hash"),
            chunk_count=int(eval_result["document"].get("chunk_count") or 1),
            warnings=list(eval_result.get("warnings") or []),
            created_by=actor,
            reason=reason[:500],
            correlation_id=correlation_id or exec_req.get("correlation_id"),
        )
        self._session.add(row)
        self._session.flush()

        if document_type == "NEWS":
            self._session.add(
                AIDocumentAnalysisNewsLinkEntity(
                    document_analysis_id=row.document_analysis_id,
                    article_id=source_document_id,
                )
            )
        else:
            self._session.add(
                AIDocumentAnalysisDisclosureLinkEntity(
                    document_analysis_id=row.document_analysis_id,
                    disclosure_id=source_document_id,
                )
            )

        self._history(
            row.document_analysis_id,
            action="AI_DOCUMENT_ANALYSIS_CREATED",
            actor=actor,
            previous=None,
            new="DRAFT_ANALYSIS",
            reason=reason,
            correlation_id=row.correlation_id,
            detail={
                "document_type": document_type,
                "source_document_key": row.source_document_key,
                "execution_request_id": row.execution_request_id,
            },
        )
        self._session.commit()
        self._session.refresh(row)
        return {
            "idempotent_replay": False,
            "analysis": self._public(row),
            "eligibility_warnings": eval_result.get("warnings"),
        }

    def dry_run(self, analysis_id: int, *, actor: str) -> dict[str, Any]:
        row = self._session.get(AIDocumentAnalysisEntity, analysis_id)
        if row is None:
            raise AIDocumentAnalysisError("NOT_FOUND", "analysis not found")
        if row.execution_request_id is None:
            raise AIDocumentAnalysisError("NO_EXECUTION", "missing execution")

        self._history(
            analysis_id,
            action="AI_DOCUMENT_ANALYSIS_DRY_RUN_STARTED",
            actor=actor,
            previous=row.analysis_status,
            new=row.analysis_status,
            correlation_id=row.correlation_id,
        )
        result = AIExecutionRunner(self._session).dry_run(
            row.execution_request_id, actor=actor
        )
        self._history(
            analysis_id,
            action="AI_DOCUMENT_ANALYSIS_DRY_RUN_COMPLETED",
            actor=actor,
            detail={
                "ok": result.get("ok"),
                "external_ai_called": False,
                "estimated_max_cost": result.get("estimated_max_cost"),
            },
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        return {
            **result,
            "analysis": self._public(row),
            "disclaimer": REFERENCE_DISCLAIMER,
            "external_ai_called": False,
        }

    async def execute(
        self,
        analysis_id: int,
        *,
        actor: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        row = self._session.get(AIDocumentAnalysisEntity, analysis_id)
        if row is None:
            raise AIDocumentAnalysisError("NOT_FOUND", "analysis not found")
        if row.execution_request_id is None:
            raise AIDocumentAnalysisError("NO_EXECUTION", "missing execution")

        # 데이터 등급 재확인
        eval_result = self._eligibility.evaluate(
            document_type=row.document_type,
            source_document_id=row.source_document_id,
            execution_mode=row.execution_mode,
            provider_code=row.provider_code or "mock",
            prompt_version_id=row.prompt_version_id,
        )
        if not eval_result["provider_policy"]["allowed"]:
            self._history(
                analysis_id,
                action="AI_DOCUMENT_ANALYSIS_DATA_POLICY_BLOCKED",
                actor=actor,
                previous=row.analysis_status,
                new="BLOCKED",
                correlation_id=row.correlation_id,
            )
            row.analysis_status = "BLOCKED"
            self._session.commit()
            raise AIDocumentAnalysisError(
                "DATA_POLICY_BLOCKED",
                str(eval_result["provider_policy"].get("reason")),
            )

        self._history(
            analysis_id,
            action="AI_DOCUMENT_ANALYSIS_EXECUTION_REQUESTED",
            actor=actor,
            previous=row.analysis_status,
            new="RUNNING",
            correlation_id=row.correlation_id,
            detail={"confirm": confirm, "mode": row.execution_mode},
        )
        row.analysis_status = "RUNNING"
        self._session.commit()

        try:
            result = await AIExecutionRunner(self._session).execute(
                row.execution_request_id,
                actor=actor,
                confirm=confirm,
            )
        except AIExecutionError as exc:
            row.analysis_status = "FAILED"
            self._history(
                analysis_id,
                action="AI_DOCUMENT_ANALYSIS_FAILED",
                actor=actor,
                previous="RUNNING",
                new="FAILED",
                reason=exc.message,
                correlation_id=row.correlation_id,
            )
            self._session.commit()
            raise AIDocumentAnalysisError(exc.code, exc.message) from exc

        self._session.refresh(row)
        exec_req = self._exec.get_request(row.execution_request_id)
        exec_result = self._exec.get_result(row.execution_request_id)
        self._apply_execution_outcome(
            row,
            actor=actor,
            exec_req=exec_req,
            exec_result=exec_result,
            normalized=eval_result.get("normalized") or {},
            runner_ok=bool(result.get("ok")),
        )
        self._session.commit()
        self._session.refresh(row)
        return {
            "ok": bool(result.get("ok")),
            "analysis": self._public(row),
            "execution": result,
            "disclaimer": REFERENCE_DISCLAIMER,
            "external_ai_called": bool(result.get("external_ai_called")),
            "mock_called": bool(result.get("mock_called")),
        }

    def _apply_execution_outcome(
        self,
        row: AIDocumentAnalysisEntity,
        *,
        actor: str,
        exec_req: dict[str, Any],
        exec_result: dict[str, Any] | None,
        normalized: dict[str, Any],
        runner_ok: bool,
    ) -> None:
        status = str(exec_req.get("status") or "")
        prev = row.analysis_status
        if status in {"SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"} and exec_result:
            payload = exec_result.get("result_payload") or {}
            result_body = (
                payload.get("result") if isinstance(payload, dict) else {}
            ) or {}
            ai_symbols = list(result_body.get("related_symbols") or [])
            resolution = resolve_entities(
                self._session,
                document_type=row.document_type,
                source_symbols=normalized.get("related_symbols"),
                source_corp_code=normalized.get("corp_code"),
                source_stock_code=normalized.get("stock_code")
                or normalized.get("symbol"),
                ai_symbols=ai_symbols,
            )
            if resolution["unresolved_entities"]:
                self._history(
                    row.document_analysis_id,
                    action="AI_DOCUMENT_ANALYSIS_ENTITY_UNRESOLVED",
                    actor=actor,
                    detail={
                        "count": len(resolution["unresolved_entities"]),
                    },
                    correlation_id=row.correlation_id,
                )

            citations = list(payload.get("citations") or [])
            citation_warnings = self._store_citations(
                row.document_analysis_id,
                citations,
                normalized_body=str(normalized.get("normalized_body") or ""),
            )
            for topic in list(result_body.get("topics") or [])[:20]:
                self._session.add(
                    AIDocumentAnalysisTopicEntity(
                        document_analysis_id=row.document_analysis_id,
                        topic_code=str(topic)[:80],
                        topic_name=str(topic)[:200],
                    )
                )
            for ent in resolution["resolved_entities"][:30]:
                self._session.add(
                    AIDocumentAnalysisEntityRow(
                        document_analysis_id=row.document_analysis_id,
                        entity_type=str(ent.get("entity_type") or "ENTITY"),
                        entity_code=ent.get("entity_code"),
                        entity_name=str(ent.get("entity_name") or "")[:200],
                        relevance=None,
                        sentiment=None,
                    )
                )

            warnings = list(exec_result.get("warnings") or []) + citation_warnings
            if status == "SUCCEEDED_WITH_WARNINGS" or warnings:
                new_status = "VALIDATED_WITH_WARNINGS"
            else:
                new_status = "VALIDATED_ANALYSIS"
            row.safe_result = sanitize_for_log(
                payload if isinstance(payload, dict) else {}
            )
            row.result_hash = exec_result.get("result_hash")
            row.confidence = exec_result.get("confidence")
            # execution_result FK는 별도 조회 없이 request 연결로 충분
            row.warnings = warnings
            row.unresolved_entities = resolution["unresolved_entities"]
            row.unmatched_symbols = resolution["unmatched_symbols"]
            row.analyzed_at = _now()
            importance = result_body.get("importance") or result_body.get(
                "event_importance"
            )
            row.risk_level = str(importance) if importance else None
            row.analysis_status = new_status
            self._history(
                row.document_analysis_id,
                action="AI_DOCUMENT_ANALYSIS_VALIDATED"
                if new_status == "VALIDATED_ANALYSIS"
                else "AI_DOCUMENT_ANALYSIS_WARNING",
                actor=actor,
                previous=prev,
                new=new_status,
                correlation_id=row.correlation_id,
            )
            self._history(
                row.document_analysis_id,
                action="AI_DOCUMENT_ANALYSIS_COMPLETED",
                actor=actor,
                previous=prev,
                new=new_status,
                correlation_id=row.correlation_id,
                detail={"tokens": exec_req.get("max_tokens")},
            )
        elif status == "BLOCKED":
            row.analysis_status = "BLOCKED"
            self._history(
                row.document_analysis_id,
                action="AI_DOCUMENT_ANALYSIS_BLOCKED",
                actor=actor,
                previous=prev,
                new="BLOCKED",
                correlation_id=row.correlation_id,
            )
        elif status == "CANCELLED":
            row.analysis_status = "CANCELLED"
            self._history(
                row.document_analysis_id,
                action="AI_DOCUMENT_ANALYSIS_CANCELLED",
                actor=actor,
                previous=prev,
                new="CANCELLED",
                correlation_id=row.correlation_id,
            )
        else:
            row.analysis_status = "FAILED" if not runner_ok else "INVALID"
            self._history(
                row.document_analysis_id,
                action="AI_DOCUMENT_ANALYSIS_FAILED",
                actor=actor,
                previous=prev,
                new=row.analysis_status,
                correlation_id=row.correlation_id,
            )

    def _store_citations(
        self,
        analysis_id: int,
        citations: list[Any],
        *,
        normalized_body: str,
    ) -> list[str]:
        warnings: list[str] = []
        for item in citations[:20]:
            if not isinstance(item, dict):
                warnings.append("invalid_citation_shape")
                continue
            source_ref = str(item.get("ref") or item.get("source") or "")[:200]
            if not source_ref:
                warnings.append("citation_missing_ref")
                continue
            # 원문 위치 검증 (가능한 범위)
            excerpt = str(item.get("excerpt") or "")
            excerpt_hash = None
            if excerpt:
                excerpt_hash = hashlib.sha256(excerpt.encode()).hexdigest()
                if excerpt not in normalized_body and source_ref not in {
                    "title",
                    "body",
                    "summary",
                }:
                    warnings.append("citation_not_found_in_source")
            self._session.add(
                AIDocumentAnalysisCitationEntity(
                    document_analysis_id=analysis_id,
                    citation_type=str(item.get("type") or "SOURCE")[:40],
                    source_ref=source_ref,
                    title=str(item.get("title") or "")[:300] or None,
                    excerpt_hash=excerpt_hash,
                    position_start=item.get("position_start"),
                    position_end=item.get("position_end"),
                )
            )
        return warnings

    def cancel(self, analysis_id: int, *, actor: str, reason: str) -> dict[str, Any]:
        row = self._session.get(AIDocumentAnalysisEntity, analysis_id)
        if row is None:
            raise AIDocumentAnalysisError("NOT_FOUND", "analysis not found")
        self._history(
            analysis_id,
            action="AI_DOCUMENT_ANALYSIS_CANCEL_REQUESTED",
            actor=actor,
            previous=row.analysis_status,
            reason=reason,
            correlation_id=row.correlation_id,
        )
        if row.execution_request_id:
            try:
                self._exec.cancel(
                    row.execution_request_id, actor=actor, reason=reason
                )
            except AIExecutionError as exc:
                raise AIDocumentAnalysisError(exc.code, exc.message) from exc
        row.analysis_status = "CANCELLED"
        self._history(
            analysis_id,
            action="AI_DOCUMENT_ANALYSIS_CANCELLED",
            actor=actor,
            new="CANCELLED",
            reason=reason,
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        return {"analysis": self._public(row)}

    def reanalyze(
        self,
        analysis_id: int,
        *,
        actor: str,
        reason: str,
        idempotency_key: str,
        force_new_version: bool = True,
    ) -> dict[str, Any]:
        """기존 결과 보존 + 새 분석. force만으로 덮어쓰지 않음."""

        old = self._session.get(AIDocumentAnalysisEntity, analysis_id)
        if old is None:
            raise AIDocumentAnalysisError("NOT_FOUND", "analysis not found")
        created = self.create(
            actor=actor,
            reason=reason,
            document_type=old.document_type,
            source_document_id=old.source_document_id,
            execution_mode=old.execution_mode,
            provider_code=old.provider_code,
            model=old.model,
            prompt_version_id=old.prompt_version_id,
            idempotency_key=idempotency_key,
            force_new_version=force_new_version,
            correlation_id=old.correlation_id,
        )
        new_row_id = created["analysis"]["id"]
        if new_row_id != old.document_analysis_id:
            prev_status = old.analysis_status
            old.analysis_status = "SUPERSEDED"
            old.superseded_at = _now()
            old.superseded_by_id = new_row_id
            self._history(
                old.document_analysis_id,
                action="AI_DOCUMENT_ANALYSIS_SUPERSEDED",
                actor=actor,
                previous=prev_status,
                new="SUPERSEDED",
                reason=reason,
                detail={"superseded_by_id": new_row_id},
                correlation_id=old.correlation_id,
            )
            self._history(
                new_row_id,
                action="AI_DOCUMENT_ANALYSIS_REANALYSIS_CREATED",
                actor=actor,
                reason=reason,
                detail={"previous_id": old.document_analysis_id},
                correlation_id=old.correlation_id,
            )
            self._session.commit()
        return created

    def get(self, analysis_id: int) -> dict[str, Any]:
        row = self._session.get(AIDocumentAnalysisEntity, analysis_id)
        if row is None:
            raise AIDocumentAnalysisError("NOT_FOUND", "analysis not found")
        return self._public(row)

    def history(self, analysis_id: int) -> list[dict[str, Any]]:
        rows = self._session.scalars(
            select(AIDocumentAnalysisHistoryEntity)
            .where(
                AIDocumentAnalysisHistoryEntity.document_analysis_id
                == analysis_id
            )
            .order_by(AIDocumentAnalysisHistoryEntity.id.desc())
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

    def list_analyses(
        self,
        *,
        document_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        stmt = select(AIDocumentAnalysisEntity).order_by(
            AIDocumentAnalysisEntity.document_analysis_id.desc()
        )
        if document_type:
            stmt = stmt.where(
                AIDocumentAnalysisEntity.document_type == document_type
            )
        rows = self._session.scalars(stmt.limit(min(limit, 200))).all()
        return [self._public(r) for r in rows]

    def compare(self, left_id: int, right_id: int) -> dict[str, Any]:
        left = self.get(left_id)
        right = self.get(right_id)
        left_result = left.get("safe_result") or {}
        right_result = right.get("safe_result") or {}
        return {
            "left": left,
            "right": right,
            "diff": {
                "provider": [left.get("provider_code"), right.get("provider_code")],
                "model": [left.get("model"), right.get("model")],
                "prompt_version_id": [
                    left.get("prompt_version_id"),
                    right.get("prompt_version_id"),
                ],
                "confidence": [left.get("confidence"), right.get("confidence")],
                "status": [
                    left.get("analysis_status"),
                    right.get("analysis_status"),
                ],
                "result_equal": left_result == right_result,
            },
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def dashboard_summary(self) -> dict[str, Any]:
        rows = self._session.scalars(
            select(AIDocumentAnalysisEntity).limit(500)
        ).all()
        today = _now().date()

        def _today(r: AIDocumentAnalysisEntity) -> bool:
            return bool(r.analyzed_at and r.analyzed_at.date() == today) or bool(
                r.created_at and r.created_at.date() == today
            )

        news_today = sum(
            1 for r in rows if r.document_type == "NEWS" and _today(r)
        )
        disc_today = sum(
            1 for r in rows if r.document_type == "DISCLOSURE" and _today(r)
        )
        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r.analysis_status] = by_status.get(r.analysis_status, 0) + 1
        confs = [float(r.confidence) for r in rows if r.confidence is not None]
        return {
            "news_analysis_today": news_today,
            "disclosure_analysis_today": disc_today,
            "running": by_status.get("RUNNING", 0),
            "queued": by_status.get("QUEUED", 0),
            "succeeded": by_status.get("VALIDATED_ANALYSIS", 0)
            + by_status.get("VALIDATED_WITH_WARNINGS", 0),
            "failed": by_status.get("FAILED", 0),
            "blocked": by_status.get("BLOCKED", 0),
            "validation_warning": by_status.get("VALIDATED_WITH_WARNINGS", 0),
            "superseded": by_status.get("SUPERSEDED", 0),
            "average_confidence": (
                round(sum(confs) / len(confs), 4) if confs else None
            ),
            "mock_vs_external": {
                "mock": sum(1 for r in rows if r.execution_mode == "MOCK"),
                "external": sum(
                    1 for r in rows if r.execution_mode == "EXTERNAL"
                ),
                "dry_run": sum(1 for r in rows if r.execution_mode == "DRY_RUN"),
            },
            "disclaimer": REFERENCE_DISCLAIMER,
            "auto_analysis_on_ingest": False,
            "external_ai_called": False,
        }


class AIAnalysisBatchService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._svc = AIDocumentAnalysisService(session)

    def create_batch(
        self,
        *,
        actor: str,
        reason: str,
        document_type: str,
        source_document_ids: list[int],
        execution_mode: str,
        provider_code: str,
        model: str | None,
        prompt_version_id: int | None,
        confirm: bool,
        idempotency_key: str,
        estimated_max_tokens: int | None = None,
        estimated_max_cost: float | None = None,
    ) -> dict[str, Any]:
        if not confirm:
            raise AIDocumentAnalysisError(
                "CONFIRM_REQUIRED", "batch requires confirm=true"
            )
        if document_type not in DOCUMENT_TYPES:
            raise AIDocumentAnalysisError(
                "INVALID_DOCUMENT_TYPE", "one document_type only"
            )
        if not source_document_ids:
            raise AIDocumentAnalysisError(
                "EMPTY_IDS", "explicit document IDs required"
            )
        # 무제한 날짜 범위 / 전체 미분석 자동선택 금지 — ID 목록만
        cap = (
            MAX_BATCH_EXTERNAL
            if execution_mode == "EXTERNAL"
            else MAX_BATCH_MOCK
        )
        cap = min(cap, HARD_BATCH_CAP)
        if len(source_document_ids) > cap:
            raise AIDocumentAnalysisError(
                "BATCH_LIMIT", f"max {cap} documents for {execution_mode}"
            )

        created: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for idx, doc_id in enumerate(source_document_ids):
            try:
                item = self._svc.create(
                    actor=actor,
                    reason=reason,
                    document_type=document_type,
                    source_document_id=int(doc_id),
                    execution_mode=execution_mode,
                    provider_code=provider_code,
                    model=model,
                    prompt_version_id=prompt_version_id,
                    idempotency_key=f"{idempotency_key}:{idx}"[:64],
                )
                created.append(item["analysis"])
            except AIDocumentAnalysisError as exc:
                errors.append(
                    {"source_document_id": doc_id, "code": exc.code, "message": exc.message}
                )

        # history marker on first
        if created:
            self._svc._history(
                created[0]["id"],
                action="AI_DOCUMENT_ANALYSIS_BATCH_CREATED",
                actor=actor,
                reason=reason,
                detail={
                    "count": len(created),
                    "errors": len(errors),
                    "mode": execution_mode,
                    "estimated_max_tokens": estimated_max_tokens,
                    "estimated_max_cost": estimated_max_cost,
                },
            )
            self._session.commit()

        return {
            "created_count": len(created),
            "error_count": len(errors),
            "items": created,
            "errors": errors,
            "cap": cap,
            "auto_execute": False,
            "disclaimer": REFERENCE_DISCLAIMER,
        }
