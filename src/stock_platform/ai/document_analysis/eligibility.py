"""STEP 11-6 — 분석 Eligibility."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.document_analysis.chunking import plan_chunks
from stock_platform.ai.document_analysis.constants import (
    MAX_DOCUMENT_CHARS,
    MAX_TOTAL_TOKENS,
)
from stock_platform.ai.document_analysis.data_policy import (
    classify_document,
    provider_allowed,
)
from stock_platform.ai.document_analysis.normalizer import AIDocumentNormalizer
from stock_platform.ai.prompt.entities import (
    AIOutputSchemaEntity,
    AIPolicyDefinitionEntity,
    AIPromptTemplateEntity,
    AIPromptTemplateVersionEntity,
)


class AIDocumentEligibilityService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._normalizer = AIDocumentNormalizer(session)

    def evaluate(
        self,
        *,
        document_type: str,
        source_document_id: int,
        execution_mode: str = "MOCK",
        provider_code: str | None = "mock",
        prompt_version_id: int | None = None,
        has_internal_notes: bool = False,
    ) -> dict[str, Any]:
        try:
            if document_type == "NEWS":
                doc = self._normalizer.load_news(source_document_id)
                task_type = "NEWS_ANALYSIS"
                schema_code = "NEWS_ANALYSIS_RESULT_V1"
                prompt_code = "NEWS_ANALYSIS_BASE"
            elif document_type == "DISCLOSURE":
                doc = self._normalizer.load_disclosure(source_document_id)
                task_type = "DISCLOSURE_ANALYSIS"
                schema_code = "DISCLOSURE_ANALYSIS_RESULT_V1"
                prompt_code = "DISCLOSURE_ANALYSIS_BASE"
            else:
                return {
                    "eligible": False,
                    "code": "INVALID_DOCUMENT_TYPE",
                    "message": "document_type must be NEWS or DISCLOSURE",
                }
        except LookupError as exc:
            return {
                "eligible": False,
                "code": str(exc),
                "message": "source document not found",
            }

        classification = classify_document(
            document_type=document_type,
            has_internal_notes=has_internal_notes,
        )
        policy = provider_allowed(
            classification=classification,
            provider_code=provider_code or "mock",
            execution_mode=execution_mode,
        )

        chunks = plan_chunks(str(doc.get("normalized_body") or ""))
        body_len = len(str(doc.get("normalized_body") or ""))
        injection = doc.get("injection") or {}

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
                AIPolicyDefinitionEntity.code == "CORE_PROMPT_SECURITY",
                AIPolicyDefinitionEntity.status == "ACTIVE",
            )
        )

        blockers: list[str] = []
        warnings: list[str] = list(chunks.get("warnings") or [])
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
        if not policy["allowed"]:
            blockers.append(str(policy.get("reason") or "DATA_POLICY_BLOCKED"))
        if injection.get("blocked"):
            blockers.append("PROMPT_INJECTION_BLOCKED")
        warnings.extend(list(injection.get("warnings") or []))
        if body_len > MAX_DOCUMENT_CHARS:
            warnings.append("document_near_size_limit")
        if doc.get("body_from_title_only"):
            warnings.append("title_summary_only_no_full_body")

        est_tokens = min(MAX_TOTAL_TOKENS, max(64, body_len // 3 + 256))
        return {
            "eligible": len(blockers) == 0,
            "blockers": blockers,
            "warnings": warnings,
            "document": {
                "document_type": document_type,
                "source_document_id": source_document_id,
                "source_document_key": doc["source_document_key"],
                "source_version": doc["source_version"],
                "content_size": body_len,
                "chunk_count": chunks["chunk_count"],
                "chunk_strategy": chunks["strategy"],
                "data_classification": classification,
                "external_transfer_allowed": policy["allowed"]
                and execution_mode == "EXTERNAL",
                "symbol": doc.get("symbol"),
                "company_id": doc.get("company_id") or doc.get("corp_code"),
                "market_type": doc.get("market_type"),
            },
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
            "provider_policy": policy,
            "estimated_max_tokens": est_tokens,
            "normalized": doc,
            "disclaimer": (
                "AI 분석 결과는 참고용이며 매매 신호 또는 주문 지시가 아닙니다."
            ),
        }
