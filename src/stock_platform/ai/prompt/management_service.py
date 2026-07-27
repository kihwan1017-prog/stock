"""STEP 11-4 — Prompt / Schema / Policy 관리 서비스."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.ai.prompt.entities import (
    AIOutputSchemaEntity,
    AIPolicyDefinitionEntity,
    AIPromptChangeHistoryEntity,
    AIPromptTemplateEntity,
    AIPromptTemplateVersionEntity,
)
from stock_platform.ai.prompt.renderer import checksum_text, validate_template_safety
from stock_platform.ai.prompt.task_types import (
    ENFORCEMENT_MODES,
    POLICY_TYPES,
    SCHEMA_STATUSES,
    TASK_TYPES,
    TEMPLATE_STATUSES,
)
from stock_platform.ai.providers.security import sanitize_for_log


class AIPromptManagementError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _schema_checksum(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AIPromptManagementService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _history(
        self,
        *,
        action: str,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
        template_id: int | None = None,
        version_id: int | None = None,
        schema_id: int | None = None,
        policy_id: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            AIPromptChangeHistoryEntity(
                prompt_template_id=template_id,
                prompt_version_id=version_id,
                output_schema_id=schema_id,
                policy_id=policy_id,
                action=action,
                detail=sanitize_for_log(detail or {}),
                changed_by=actor,
                reason=(reason or "")[:500],
                correlation_id=correlation_id,
            )
        )

    # ---- dashboard aggregates (no raw templates) ----

    def dashboard_stats(self) -> dict[str, Any]:
        def count(model, status: str | None = None) -> int:
            stmt = select(func.count()).select_from(model)
            if status:
                stmt = stmt.where(model.status == status)
            return int(self._session.scalar(stmt) or 0)

        return {
            "active_prompt_count": count(AIPromptTemplateEntity, "ACTIVE"),
            "draft_prompt_count": count(AIPromptTemplateEntity, "DRAFT"),
            "active_policy_count": count(AIPolicyDefinitionEntity, "ACTIVE"),
            "active_schema_count": count(AIOutputSchemaEntity, "ACTIVE"),
            "invalid_schema_count": 0,
            "prompt_version_drift": 0,
            "external_calls_on_read": 0,
        }

    # ---- templates ----

    def list_templates(self) -> list[dict[str, Any]]:
        rows = list(
            self._session.scalars(
                select(AIPromptTemplateEntity).order_by(
                    AIPromptTemplateEntity.code
                )
            )
        )
        return [self._public_template(r) for r in rows]

    def get_template(self, template_id: int) -> dict[str, Any]:
        row = self._session.get(AIPromptTemplateEntity, template_id)
        if row is None:
            raise AIPromptManagementError("NOT_FOUND", "Template not found")
        item = self._public_template(row)
        item["versions"] = self.list_versions(template_id)
        return item

    def _public_template(self, row: AIPromptTemplateEntity) -> dict[str, Any]:
        return {
            "id": row.prompt_template_id,
            "code": row.code,
            "name": row.name,
            "task_type": row.task_type,
            "description": row.description,
            "status": row.status,
            "active_version_id": row.active_version_id,
            "lock_version": row.lock_version,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "updated_by": row.updated_by,
        }

    def create_template(
        self,
        *,
        code: str,
        name: str,
        task_type: str,
        actor: str,
        reason: str,
        description: str = "",
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise AIPromptManagementError("REASON_REQUIRED", "reason required")
        code_n = code.strip().upper()
        if task_type not in TASK_TYPES:
            raise AIPromptManagementError("INVALID_TASK_TYPE", "Unknown task type")
        exists = self._session.scalar(
            select(AIPromptTemplateEntity).where(
                AIPromptTemplateEntity.code == code_n
            )
        )
        if exists:
            raise AIPromptManagementError("DUPLICATE_CODE", "code already exists")
        row = AIPromptTemplateEntity(
            code=code_n,
            name=name.strip()[:200],
            task_type=task_type,
            description=(description or "")[:2000],
            status="DRAFT",
            created_by=actor,
            updated_by=actor,
        )
        self._session.add(row)
        self._session.flush()
        corr = correlation_id or str(uuid4())
        self._history(
            action="AI_PROMPT_TEMPLATE_CREATED",
            actor=actor,
            reason=reason,
            correlation_id=corr,
            template_id=row.prompt_template_id,
            detail={"code": code_n, "task_type": task_type},
        )
        self._session.commit()
        return self.get_template(row.prompt_template_id)

    def update_template(
        self,
        template_id: int,
        *,
        actor: str,
        reason: str,
        expected_version: int | None = None,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise AIPromptManagementError("REASON_REQUIRED", "reason required")
        row = self._session.get(AIPromptTemplateEntity, template_id)
        if row is None:
            raise AIPromptManagementError("NOT_FOUND", "Template not found")
        if expected_version is not None and row.lock_version != expected_version:
            raise AIPromptManagementError(
                "VERSION_CONFLICT", "Optimistic lock conflict"
            )
        if name is not None:
            row.name = name.strip()[:200]
        if description is not None:
            row.description = description[:2000]
        if status is not None:
            if status not in TEMPLATE_STATUSES:
                raise AIPromptManagementError("INVALID_STATUS", "bad status")
            # STRATEGY_DRAFT 템플릿 ACTIVE는 허용하되 호출은 별도 STEP
            row.status = status
        row.lock_version = int(row.lock_version) + 1
        row.updated_by = actor
        row.updated_at = _now()
        self._history(
            action="AI_PROMPT_TEMPLATE_UPDATED",
            actor=actor,
            reason=reason,
            correlation_id=correlation_id or str(uuid4()),
            template_id=template_id,
            detail={"status": row.status, "lock_version": row.lock_version},
        )
        self._session.commit()
        return self.get_template(template_id)

    # ---- versions ----

    def list_versions(self, template_id: int) -> list[dict[str, Any]]:
        rows = list(
            self._session.scalars(
                select(AIPromptTemplateVersionEntity)
                .where(
                    AIPromptTemplateVersionEntity.prompt_template_id
                    == template_id
                )
                .order_by(AIPromptTemplateVersionEntity.version.desc())
            )
        )
        return [self._public_version(r, include_body=False) for r in rows]

    def get_version(
        self, version_id: int, *, include_body: bool = True
    ) -> dict[str, Any]:
        row = self._session.get(AIPromptTemplateVersionEntity, version_id)
        if row is None:
            raise AIPromptManagementError("NOT_FOUND", "Version not found")
        return self._public_version(row, include_body=include_body)

    def _public_version(
        self, row: AIPromptTemplateVersionEntity, *, include_body: bool
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": row.prompt_template_version_id,
            "prompt_template_id": row.prompt_template_id,
            "version": row.version,
            "status": row.status,
            "checksum": row.checksum,
            "output_schema_id": row.output_schema_id,
            "policy_id": row.policy_id,
            "required_capabilities": row.required_capabilities or [],
            "change_reason": row.change_reason,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        if include_body:
            data.update(
                {
                    "system_template": row.system_template,
                    "user_template": row.user_template,
                    "context_template": row.context_template,
                    "safety_instruction": row.safety_instruction,
                    "output_instruction": row.output_instruction,
                    "variable_schema": row.variable_schema,
                }
            )
        return data

    def create_version(
        self,
        template_id: int,
        *,
        actor: str,
        reason: str,
        system_template: str,
        user_template: str,
        context_template: str = "",
        safety_instruction: str = "",
        output_instruction: str = "",
        variable_schema: dict[str, Any] | None = None,
        required_capabilities: list[str] | None = None,
        output_schema_id: int | None = None,
        policy_id: int | None = None,
        allow_duplicate_checksum: bool = False,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise AIPromptManagementError("REASON_REQUIRED", "reason required")
        tmpl = self._session.get(AIPromptTemplateEntity, template_id)
        if tmpl is None:
            raise AIPromptManagementError("NOT_FOUND", "Template not found")
        for field, text in (
            ("system", system_template),
            ("user", user_template),
            ("context", context_template or ""),
        ):
            validate_template_safety(text, field=field)

        checksum = checksum_text(
            system_template,
            user_template,
            context_template or "",
            safety_instruction or "",
            output_instruction or "",
            json.dumps(variable_schema or {}, sort_keys=True),
        )
        if not allow_duplicate_checksum:
            dup = self._session.scalar(
                select(AIPromptTemplateVersionEntity).where(
                    AIPromptTemplateVersionEntity.prompt_template_id
                    == template_id,
                    AIPromptTemplateVersionEntity.checksum == checksum,
                )
            )
            if dup is not None:
                raise AIPromptManagementError(
                    "DUPLICATE_CONTENT",
                    "Identical content version already exists",
                )

        max_ver = self._session.scalar(
            select(func.max(AIPromptTemplateVersionEntity.version)).where(
                AIPromptTemplateVersionEntity.prompt_template_id == template_id
            )
        )
        next_ver = int(max_ver or 0) + 1
        if output_schema_id is not None:
            if self._session.get(AIOutputSchemaEntity, output_schema_id) is None:
                raise AIPromptManagementError("SCHEMA_NOT_FOUND", "schema missing")
        if policy_id is not None:
            if self._session.get(AIPolicyDefinitionEntity, policy_id) is None:
                raise AIPromptManagementError("POLICY_NOT_FOUND", "policy missing")

        row = AIPromptTemplateVersionEntity(
            prompt_template_id=template_id,
            version=next_ver,
            system_template=system_template,
            user_template=user_template,
            context_template=context_template or "",
            safety_instruction=safety_instruction or "",
            output_instruction=output_instruction or "",
            variable_schema=variable_schema,
            required_capabilities=required_capabilities or [],
            output_schema_id=output_schema_id,
            policy_id=policy_id,
            change_reason=reason[:500],
            checksum=checksum,
            status="DRAFT",
            created_by=actor,
        )
        self._session.add(row)
        self._session.flush()
        tmpl.lock_version = int(tmpl.lock_version) + 1
        tmpl.updated_by = actor
        self._history(
            action="AI_PROMPT_VERSION_CREATED",
            actor=actor,
            reason=reason,
            correlation_id=correlation_id or str(uuid4()),
            template_id=template_id,
            version_id=row.prompt_template_version_id,
            detail={"version": next_ver, "checksum": checksum[:16]},
        )
        self._session.commit()
        return self.get_version(row.prompt_template_version_id)

    def activate_version(
        self,
        version_id: int,
        *,
        actor: str,
        reason: str,
        confirm: bool,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not confirm:
            raise AIPromptManagementError("CONFIRM_REQUIRED", "confirm=true required")
        if not reason.strip():
            raise AIPromptManagementError("REASON_REQUIRED", "reason required")
        ver = self._session.get(AIPromptTemplateVersionEntity, version_id)
        if ver is None:
            raise AIPromptManagementError("NOT_FOUND", "Version not found")
        if ver.status == "ARCHIVED":
            raise AIPromptManagementError("ARCHIVED", "Cannot activate archived")
        tmpl = self._session.get(
            AIPromptTemplateEntity, ver.prompt_template_id
        )
        assert tmpl is not None
        # 이전 active version → DRAFT 유지(내용 immutable), 템플릿 active pointer만 변경
        ver.status = "ACTIVE"
        tmpl.active_version_id = version_id
        tmpl.status = "ACTIVE"
        tmpl.updated_by = actor
        tmpl.lock_version = int(tmpl.lock_version) + 1
        self._history(
            action="AI_PROMPT_VERSION_ACTIVATED",
            actor=actor,
            reason=reason,
            correlation_id=correlation_id or str(uuid4()),
            template_id=tmpl.prompt_template_id,
            version_id=version_id,
            detail={"version": ver.version},
        )
        self._session.commit()
        return {
            "template": self._public_template(tmpl),
            "version": self._public_version(ver, include_body=False),
            "auto_ai_called": False,
        }

    def archive_version(
        self,
        version_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise AIPromptManagementError("REASON_REQUIRED", "reason required")
        ver = self._session.get(AIPromptTemplateVersionEntity, version_id)
        if ver is None:
            raise AIPromptManagementError("NOT_FOUND", "Version not found")
        tmpl = self._session.get(
            AIPromptTemplateEntity, ver.prompt_template_id
        )
        assert tmpl is not None
        if tmpl.active_version_id == version_id:
            raise AIPromptManagementError(
                "ACTIVE_IN_USE",
                "Cannot archive active version; activate another first",
            )
        ver.status = "ARCHIVED"
        self._history(
            action="AI_PROMPT_VERSION_ARCHIVED",
            actor=actor,
            reason=reason,
            correlation_id=correlation_id or str(uuid4()),
            template_id=tmpl.prompt_template_id,
            version_id=version_id,
            detail={"version": ver.version},
        )
        self._session.commit()
        return self._public_version(ver, include_body=False)

    # ---- schemas ----

    def list_schemas(self) -> list[dict[str, Any]]:
        rows = list(
            self._session.scalars(
                select(AIOutputSchemaEntity).order_by(AIOutputSchemaEntity.code)
            )
        )
        return [self._public_schema(r, include_body=False) for r in rows]

    def get_schema(
        self, schema_id: int, *, include_body: bool = True
    ) -> dict[str, Any]:
        row = self._session.get(AIOutputSchemaEntity, schema_id)
        if row is None:
            raise AIPromptManagementError("NOT_FOUND", "Schema not found")
        return self._public_schema(row, include_body=include_body)

    def _public_schema(
        self, row: AIOutputSchemaEntity, *, include_body: bool
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": row.output_schema_id,
            "code": row.code,
            "name": row.name,
            "task_type": row.task_type,
            "schema_version": row.schema_version,
            "status": row.status,
            "strict_mode": row.strict_mode,
            "additional_properties_allowed": row.additional_properties_allowed,
            "checksum": row.checksum,
            "lock_version": row.lock_version,
            "compatibility": row.compatibility,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        if include_body:
            data["json_schema"] = row.json_schema
        return data

    def create_schema(
        self,
        *,
        code: str,
        name: str,
        task_type: str,
        json_schema: dict[str, Any],
        actor: str,
        reason: str,
        schema_version: str = "1.0",
        strict_mode: bool = True,
        additional_properties_allowed: bool = False,
        status: str = "DRAFT",
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise AIPromptManagementError("REASON_REQUIRED", "reason required")
        if task_type not in TASK_TYPES:
            raise AIPromptManagementError("INVALID_TASK_TYPE", "bad task type")
        if status not in SCHEMA_STATUSES:
            raise AIPromptManagementError("INVALID_STATUS", "bad status")
        if not isinstance(json_schema, dict) or not json_schema:
            raise AIPromptManagementError("INVALID_SCHEMA", "json_schema required")
        code_n = code.strip().upper()
        if self._session.scalar(
            select(AIOutputSchemaEntity).where(AIOutputSchemaEntity.code == code_n)
        ):
            raise AIPromptManagementError("DUPLICATE_CODE", "code exists")
        if not additional_properties_allowed:
            json_schema = {
                **json_schema,
                "additionalProperties": False,
            }
        checksum = _schema_checksum(json_schema)
        row = AIOutputSchemaEntity(
            code=code_n,
            name=name[:200],
            task_type=task_type,
            schema_version=schema_version[:20],
            json_schema=json_schema,
            strict_mode=strict_mode,
            additional_properties_allowed=additional_properties_allowed,
            status=status,
            checksum=checksum,
            created_by=actor,
            updated_by=actor,
        )
        self._session.add(row)
        self._session.flush()
        self._history(
            action="AI_OUTPUT_SCHEMA_CREATED",
            actor=actor,
            reason=reason,
            correlation_id=correlation_id or str(uuid4()),
            schema_id=row.output_schema_id,
            detail={"code": code_n, "checksum": checksum[:16]},
        )
        self._session.commit()
        return self.get_schema(row.output_schema_id)

    def update_schema(
        self,
        schema_id: int,
        *,
        actor: str,
        reason: str,
        expected_version: int | None = None,
        name: str | None = None,
        json_schema: dict[str, Any] | None = None,
        status: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise AIPromptManagementError("REASON_REQUIRED", "reason required")
        row = self._session.get(AIOutputSchemaEntity, schema_id)
        if row is None:
            raise AIPromptManagementError("NOT_FOUND", "Schema not found")
        if expected_version is not None and row.lock_version != expected_version:
            raise AIPromptManagementError(
                "VERSION_CONFLICT", "Optimistic lock conflict"
            )
        if name is not None:
            row.name = name[:200]
        if json_schema is not None:
            if not isinstance(json_schema, dict):
                raise AIPromptManagementError("INVALID_SCHEMA", "bad schema")
            row.json_schema = json_schema
            row.checksum = _schema_checksum(json_schema)
        if status is not None:
            if status not in SCHEMA_STATUSES:
                raise AIPromptManagementError("INVALID_STATUS", "bad status")
            row.status = status
        row.lock_version = int(row.lock_version) + 1
        row.updated_by = actor
        self._history(
            action="AI_OUTPUT_SCHEMA_UPDATED",
            actor=actor,
            reason=reason,
            correlation_id=correlation_id or str(uuid4()),
            schema_id=schema_id,
            detail={"lock_version": row.lock_version},
        )
        self._session.commit()
        return self.get_schema(schema_id)

    # ---- policies ----

    def list_policies(self) -> list[dict[str, Any]]:
        rows = list(
            self._session.scalars(
                select(AIPolicyDefinitionEntity).order_by(
                    AIPolicyDefinitionEntity.code,
                    AIPolicyDefinitionEntity.version.desc(),
                )
            )
        )
        return [self._public_policy(r, include_rules=False) for r in rows]

    def get_policy(
        self, policy_id: int, *, include_rules: bool = True
    ) -> dict[str, Any]:
        row = self._session.get(AIPolicyDefinitionEntity, policy_id)
        if row is None:
            raise AIPromptManagementError("NOT_FOUND", "Policy not found")
        return self._public_policy(row, include_rules=include_rules)

    def _public_policy(
        self, row: AIPolicyDefinitionEntity, *, include_rules: bool
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": row.policy_definition_id,
            "code": row.code,
            "name": row.name,
            "policy_type": row.policy_type,
            "version": row.version,
            "severity": row.severity,
            "enforcement_mode": row.enforcement_mode,
            "status": row.status,
            "is_core": row.is_core,
            "lock_version": row.lock_version,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        if include_rules:
            data["rules"] = row.rules
            data["change_reason"] = row.change_reason
        return data

    def create_policy(
        self,
        *,
        code: str,
        name: str,
        policy_type: str,
        rules: dict[str, Any],
        actor: str,
        reason: str,
        severity: str = "HIGH",
        enforcement_mode: str = "BLOCK",
        status: str = "DRAFT",
        is_core: bool = False,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise AIPromptManagementError("REASON_REQUIRED", "reason required")
        if policy_type not in POLICY_TYPES:
            raise AIPromptManagementError("INVALID_POLICY_TYPE", "bad type")
        if enforcement_mode not in ENFORCEMENT_MODES:
            raise AIPromptManagementError("INVALID_ENFORCEMENT", "bad mode")
        code_n = code.strip().upper()
        max_ver = self._session.scalar(
            select(func.max(AIPolicyDefinitionEntity.version)).where(
                AIPolicyDefinitionEntity.code == code_n
            )
        )
        row = AIPolicyDefinitionEntity(
            code=code_n,
            name=name[:200],
            policy_type=policy_type,
            version=int(max_ver or 0) + 1,
            rules=rules or {},
            severity=severity,
            enforcement_mode=enforcement_mode,
            status=status,
            is_core=is_core,
            change_reason=reason[:500],
            created_by=actor,
            updated_by=actor,
        )
        self._session.add(row)
        self._session.flush()
        self._history(
            action="AI_POLICY_CREATED",
            actor=actor,
            reason=reason,
            correlation_id=correlation_id or str(uuid4()),
            policy_id=row.policy_definition_id,
            detail={"code": code_n, "version": row.version},
        )
        self._session.commit()
        return self.get_policy(row.policy_definition_id)

    def activate_policy(
        self,
        policy_id: int,
        *,
        actor: str,
        reason: str,
        confirm: bool,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not confirm:
            raise AIPromptManagementError("CONFIRM_REQUIRED", "confirm required")
        if not reason.strip():
            raise AIPromptManagementError("REASON_REQUIRED", "reason required")
        row = self._session.get(AIPolicyDefinitionEntity, policy_id)
        if row is None:
            raise AIPromptManagementError("NOT_FOUND", "Policy not found")
        # 동일 code의 다른 ACTIVE → INACTIVE (core도 버전 교체는 허용, 전부 비활성은 불가)
        others = list(
            self._session.scalars(
                select(AIPolicyDefinitionEntity).where(
                    AIPolicyDefinitionEntity.code == row.code,
                    AIPolicyDefinitionEntity.status == "ACTIVE",
                    AIPolicyDefinitionEntity.policy_definition_id != policy_id,
                )
            )
        )
        for other in others:
            other.status = "INACTIVE"
        row.status = "ACTIVE"
        row.updated_by = actor
        row.lock_version = int(row.lock_version) + 1
        row.change_reason = reason[:500]
        self._history(
            action="AI_POLICY_ACTIVATED",
            actor=actor,
            reason=reason,
            correlation_id=correlation_id or str(uuid4()),
            policy_id=policy_id,
            detail={"code": row.code, "version": row.version},
        )
        self._session.commit()
        return self.get_policy(policy_id)

    def deactivate_policy(
        self,
        policy_id: int,
        *,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise AIPromptManagementError("REASON_REQUIRED", "reason required")
        row = self._session.get(AIPolicyDefinitionEntity, policy_id)
        if row is None:
            raise AIPromptManagementError("NOT_FOUND", "Policy not found")
        if row.is_core and row.status == "ACTIVE":
            # core 전부 비활성 방지: 동일 code에 다른 ACTIVE가 없으면 차단
            raise AIPromptManagementError(
                "CORE_POLICY_PROTECTED",
                "Core policy cannot be deactivated; activate a newer version instead",
            )
        row.status = "INACTIVE"
        row.updated_by = actor
        self._history(
            action="AI_POLICY_UPDATED",
            actor=actor,
            reason=reason,
            policy_id=policy_id,
            detail={"status": "INACTIVE"},
        )
        self._session.commit()
        return self.get_policy(policy_id)
