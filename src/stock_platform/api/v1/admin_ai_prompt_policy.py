"""STEP 11-4 — Admin AI Prompt / Schema / Policy / Preview API."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.prompt.management_service import (
    AIPromptManagementError,
    AIPromptManagementService,
)
from stock_platform.ai.prompt.preview_service import AIExecutionPreviewService
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.common.rate_limit import enforce_rate_limit
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/ai",
    tags=["Admin AI Prompt Policy Schema"],
    dependencies=[Depends(require_admin)],
)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    correlation_id: str | None = None
    confirm: bool = False


class TemplateCreateBody(BaseModel):
    code: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    task_type: str = Field(min_length=2, max_length=60)
    description: str = ""
    reason: str = Field(min_length=1, max_length=500)
    correlation_id: str | None = None


class TemplatePatchBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    expected_version: int | None = None
    name: str | None = None
    description: str | None = None
    status: str | None = None
    correlation_id: str | None = None


class VersionCreateBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    system_template: str = Field(min_length=1, max_length=50000)
    user_template: str = Field(min_length=1, max_length=50000)
    context_template: str = ""
    safety_instruction: str = ""
    output_instruction: str = ""
    variable_schema: dict[str, Any] | None = None
    required_capabilities: list[str] | None = None
    output_schema_id: int | None = None
    policy_id: int | None = None
    correlation_id: str | None = None


class SchemaCreateBody(BaseModel):
    code: str
    name: str
    task_type: str
    json_schema: dict[str, Any]
    reason: str = Field(min_length=1, max_length=500)
    schema_version: str = "1.0"
    status: str = "DRAFT"
    strict_mode: bool = True
    additional_properties_allowed: bool = False
    correlation_id: str | None = None


class SchemaPatchBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    expected_version: int | None = None
    name: str | None = None
    json_schema: dict[str, Any] | None = None
    status: str | None = None
    correlation_id: str | None = None


class SchemaValidateBody(BaseModel):
    sample: dict[str, Any] | str
    reason: str = Field(default="validate", max_length=500)


class PolicyCreateBody(BaseModel):
    code: str
    name: str
    policy_type: str
    rules: dict[str, Any]
    reason: str = Field(min_length=1, max_length=500)
    severity: str = "HIGH"
    enforcement_mode: str = "BLOCK"
    status: str = "DRAFT"
    correlation_id: str | None = None


class PreviewRenderBody(BaseModel):
    version_id: int
    variables: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=500)


class PreviewValidateInputBody(BaseModel):
    version_id: int
    variables: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="validate-input", max_length=500)


class PreviewParseBody(BaseModel):
    raw: str = Field(min_length=1, max_length=100000)
    reason: str = Field(default="parse", max_length=500)


class PreviewValidateResponseBody(BaseModel):
    raw: str = Field(min_length=1, max_length=100000)
    schema_id: int | None = None
    policy_id: int | None = None
    expected_task_type: str | None = None
    reason: str = Field(default="validate-response", max_length=500)


def _audit(
    session: Session,
    *,
    event_type: str,
    actor: str,
    detail: dict[str, Any],
) -> None:
    try:
        AuditLogService(session).record(
            event_type=event_type,
            actor=actor,
            detail=sanitize_for_log(detail),
        )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


def _raise(exc: AIPromptManagementError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    if exc.code == "VERSION_CONFLICT":
        code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=code, detail={"code": exc.code, "message": exc.message}
    )


# ---- Prompt templates ----


@router.get("/prompt-templates")
def list_templates(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIPromptManagementService(session).list_templates()
    return {"count": len(items), "items": items}


@router.get("/prompt-templates/{template_id}")
def get_template(
    template_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AIPromptManagementService(session).get_template(template_id)
    except AIPromptManagementError as exc:
        _raise(exc)
        raise


@router.post("/prompt-templates")
def create_template(
    body: TemplateCreateBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, scope=f"ai-prompt-write:{user.user_id}", limit=30, window_seconds=60
    )
    actor = admin_actor_label(user)
    try:
        result = AIPromptManagementService(session).create_template(
            code=body.code,
            name=body.name,
            task_type=body.task_type,
            description=body.description,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
    except AIPromptManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_PROMPT_TEMPLATE_CREATED",
        actor=actor,
        detail={"id": result.get("id"), "code": body.code},
    )
    return result


@router.patch("/prompt-templates/{template_id}")
def patch_template(
    template_id: int,
    body: TemplatePatchBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, scope=f"ai-prompt-write:{user.user_id}", limit=30, window_seconds=60
    )
    actor = admin_actor_label(user)
    try:
        result = AIPromptManagementService(session).update_template(
            template_id,
            actor=actor,
            reason=body.reason,
            expected_version=body.expected_version,
            name=body.name,
            description=body.description,
            status=body.status,
            correlation_id=body.correlation_id,
        )
    except AIPromptManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_PROMPT_TEMPLATE_UPDATED",
        actor=actor,
        detail={"id": template_id},
    )
    return result


@router.post("/prompt-templates/{template_id}/versions")
def create_version(
    template_id: int,
    body: VersionCreateBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, scope=f"ai-prompt-write:{user.user_id}", limit=30, window_seconds=60
    )
    actor = admin_actor_label(user)
    try:
        result = AIPromptManagementService(session).create_version(
            template_id,
            actor=actor,
            reason=body.reason,
            system_template=body.system_template,
            user_template=body.user_template,
            context_template=body.context_template,
            safety_instruction=body.safety_instruction,
            output_instruction=body.output_instruction,
            variable_schema=body.variable_schema,
            required_capabilities=body.required_capabilities,
            output_schema_id=body.output_schema_id,
            policy_id=body.policy_id,
            correlation_id=body.correlation_id,
        )
    except AIPromptManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_PROMPT_VERSION_CREATED",
        actor=actor,
        detail={
            "template_id": template_id,
            "version_id": result.get("id"),
            "checksum": (result.get("checksum") or "")[:16],
        },
    )
    return result


@router.get("/prompt-templates/{template_id}/versions")
def list_versions(
    template_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIPromptManagementService(session).list_versions(template_id)
    return {"count": len(items), "items": items}


@router.get("/prompt-versions/{version_id}")
def get_version(
    version_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AIPromptManagementService(session).get_version(version_id)
    except AIPromptManagementError as exc:
        _raise(exc)
        raise


@router.post("/prompt-versions/{version_id}/activate")
def activate_version(
    version_id: int,
    body: ReasonBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, scope=f"ai-prompt-activate:{user.user_id}", limit=10, window_seconds=60
    )
    actor = admin_actor_label(user)
    try:
        result = AIPromptManagementService(session).activate_version(
            version_id,
            actor=actor,
            reason=body.reason,
            confirm=body.confirm,
            correlation_id=body.correlation_id,
        )
    except AIPromptManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_PROMPT_VERSION_ACTIVATED",
        actor=actor,
        detail={"version_id": version_id, "auto_ai_called": False},
    )
    return result


@router.post("/prompt-versions/{version_id}/archive")
def archive_version(
    version_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIPromptManagementService(session).archive_version(
            version_id,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
    except AIPromptManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_PROMPT_VERSION_ARCHIVED",
        actor=actor,
        detail={"version_id": version_id},
    )
    return result


# ---- Schemas ----


@router.get("/output-schemas")
def list_schemas(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIPromptManagementService(session).list_schemas()
    return {"count": len(items), "items": items}


@router.get("/output-schemas/{schema_id}")
def get_schema(
    schema_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AIPromptManagementService(session).get_schema(schema_id)
    except AIPromptManagementError as exc:
        _raise(exc)
        raise


@router.post("/output-schemas")
def create_schema(
    body: SchemaCreateBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, scope=f"ai-schema-write:{user.user_id}", limit=30, window_seconds=60
    )
    actor = admin_actor_label(user)
    try:
        result = AIPromptManagementService(session).create_schema(
            code=body.code,
            name=body.name,
            task_type=body.task_type,
            json_schema=body.json_schema,
            actor=actor,
            reason=body.reason,
            schema_version=body.schema_version,
            strict_mode=body.strict_mode,
            additional_properties_allowed=body.additional_properties_allowed,
            status=body.status,
            correlation_id=body.correlation_id,
        )
    except AIPromptManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_OUTPUT_SCHEMA_CREATED",
        actor=actor,
        detail={"id": result.get("id"), "code": body.code},
    )
    return result


@router.patch("/output-schemas/{schema_id}")
def patch_schema(
    schema_id: int,
    body: SchemaPatchBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIPromptManagementService(session).update_schema(
            schema_id,
            actor=actor,
            reason=body.reason,
            expected_version=body.expected_version,
            name=body.name,
            json_schema=body.json_schema,
            status=body.status,
            correlation_id=body.correlation_id,
        )
    except AIPromptManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_OUTPUT_SCHEMA_UPDATED",
        actor=actor,
        detail={"id": schema_id},
    )
    return result


@router.post("/output-schemas/{schema_id}/validate")
def validate_schema_sample(
    schema_id: int,
    body: SchemaValidateBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    raw = (
        body.sample
        if isinstance(body.sample, str)
        else __import__("json").dumps(body.sample, ensure_ascii=False)
    )
    result = AIExecutionPreviewService(session).validate_response(
        raw=raw,
        schema_id=schema_id,
    )
    _audit(
        session,
        event_type="AI_OUTPUT_SCHEMA_VALIDATED",
        actor=actor,
        detail={
            "schema_id": schema_id,
            "status": result.get("status"),
            "code": result.get("code"),
        },
    )
    return result


# ---- Policies ----


@router.get("/policies")
def list_policies(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIPromptManagementService(session).list_policies()
    return {"count": len(items), "items": items}


@router.get("/policies/{policy_id}")
def get_policy(
    policy_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AIPromptManagementService(session).get_policy(policy_id)
    except AIPromptManagementError as exc:
        _raise(exc)
        raise


@router.post("/policies")
def create_policy(
    body: PolicyCreateBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, scope=f"ai-policy-write:{user.user_id}", limit=30, window_seconds=60
    )
    actor = admin_actor_label(user)
    try:
        result = AIPromptManagementService(session).create_policy(
            code=body.code,
            name=body.name,
            policy_type=body.policy_type,
            rules=body.rules,
            actor=actor,
            reason=body.reason,
            severity=body.severity,
            enforcement_mode=body.enforcement_mode,
            status=body.status,
            correlation_id=body.correlation_id,
        )
    except AIPromptManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_POLICY_CREATED",
        actor=actor,
        detail={"id": result.get("id"), "code": body.code},
    )
    return result


@router.post("/policies/{policy_id}/activate")
def activate_policy(
    policy_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIPromptManagementService(session).activate_policy(
            policy_id,
            actor=actor,
            reason=body.reason,
            confirm=body.confirm,
            correlation_id=body.correlation_id,
        )
    except AIPromptManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_POLICY_ACTIVATED",
        actor=actor,
        detail={"policy_id": policy_id},
    )
    return result


# ---- Preview (no external AI) ----


@router.post("/prompt-preview/render")
def preview_render(
    body: PreviewRenderBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, scope=f"ai-prompt-preview:{user.user_id}", limit=20, window_seconds=60
    )
    actor = admin_actor_label(user)
    try:
        result = AIExecutionPreviewService(session).render(
            version_id=body.version_id,
            variables=body.variables,
        )
    except AIPromptManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_PROMPT_RENDER_PREVIEWED",
        actor=actor,
        detail={
            "version_id": body.version_id,
            "rendered_prompt_hash": result.get("rendered_prompt_hash"),
            "blocked": result.get("blocked"),
            "external_ai_called": False,
        },
    )
    return result


@router.post("/prompt-preview/validate-input")
def preview_validate_input(
    body: PreviewValidateInputBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    result = AIExecutionPreviewService(session).validate_input(
        version_id=body.version_id,
        variables=body.variables,
    )
    _audit(
        session,
        event_type="AI_PROMPT_INPUT_VALIDATED",
        actor=actor,
        detail={
            "version_id": body.version_id,
            "ok": result.get("ok"),
            "external_ai_called": False,
        },
    )
    return result


@router.post("/prompt-preview/parse-response")
def preview_parse(
    body: PreviewParseBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    result = AIExecutionPreviewService(session).parse_response(raw=body.raw)
    _audit(
        session,
        event_type="AI_RESPONSE_PARSE_PREVIEWED",
        actor=actor,
        detail={"ok": result.get("ok"), "code": result.get("code")},
    )
    return result


@router.post("/prompt-preview/validate-response")
def preview_validate_response(
    body: PreviewValidateResponseBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIExecutionPreviewService(session).validate_response(
            raw=body.raw,
            schema_id=body.schema_id,
            policy_id=body.policy_id,
            expected_task_type=body.expected_task_type,
        )
    except AIPromptManagementError as exc:
        _raise(exc)
        raise
    event = "AI_RESPONSE_VALIDATED"
    if result.get("status") == "BLOCKED":
        event = "AI_POLICY_BLOCKED_OUTPUT"
    elif result.get("status") == "INVALID":
        event = "AI_SCHEMA_VALIDATION_FAILED"
    _audit(
        session,
        event_type=event,
        actor=actor,
        detail={
            "status": result.get("status"),
            "code": result.get("code"),
            "external_ai_called": False,
        },
    )
    return result


@router.get("/prompt-meta/stats")
def prompt_meta_stats(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    return AIPromptManagementService(session).dashboard_stats()
