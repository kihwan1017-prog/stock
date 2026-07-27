"""STEP 11-3 — Admin AI Provider Configuration & Credential Vault API."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.ai.providers.credential_verify_service import verify_credential
from stock_platform.ai.providers.management_service import (
    AIProviderManagementError,
    AIProviderManagementService,
)
from stock_platform.ai.providers.registry_loader import reload_ai_manager_from_db
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.api.deps_admin import AuditLogService, require_admin
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.common.rate_limit import enforce_rate_limit
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/admin/ai/provider-configurations",
    tags=["Admin AI Provider Configurations"],
    dependencies=[Depends(require_admin)],
)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    correlation_id: str | None = Field(default=None, max_length=64)
    confirm: bool = False
    idempotency_key: str | None = Field(default=None, max_length=64)


class ConfigUpsertBody(BaseModel):
    provider_code: str = Field(min_length=2, max_length=40)
    reason: str = Field(min_length=1, max_length=500)
    correlation_id: str | None = None
    expected_version: int | None = None
    display_name: str | None = None
    model: str | None = None
    endpoint: str | None = None
    priority: int | None = None
    timeout_sec: float | None = None
    retry_max: int | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    health_check_enabled: bool | None = None
    health_check_interval_sec: int | None = None


class CredentialStoreBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    correlation_id: str | None = None
    api_key: str | None = Field(default=None, max_length=4096)
    custom_headers: dict[str, str] | None = None


class CredentialVerifyBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    correlation_id: str | None = None
    credential_id: int | None = None


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


def _raise(exc: AIProviderManagementError) -> None:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    if exc.code == "VERSION_CONFLICT":
        code = status.HTTP_409_CONFLICT
    raise HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message})


@router.get("")
def list_configs(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    items = AIProviderManagementService(session).list_configurations()
    return {"count": len(items), "items": items}


@router.get("/{config_id}")
def get_config(
    config_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return AIProviderManagementService(session).get_configuration(config_id)
    except AIProviderManagementError as exc:
        _raise(exc)
        raise


@router.post("")
def upsert_config(
    body: ConfigUpsertBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, scope=f"ai-config-write:{user.user_id}", limit=30, window_seconds=60
    )
    actor = admin_actor_label(user)
    try:
        result = AIProviderManagementService(session).create_or_update_configuration(
            provider_code=body.provider_code,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
            expected_version=body.expected_version,
            display_name=body.display_name,
            model=body.model,
            endpoint=body.endpoint,
            priority=body.priority,
            timeout_sec=body.timeout_sec,
            retry_max=body.retry_max,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            health_check_enabled=body.health_check_enabled,
            health_check_interval_sec=body.health_check_interval_sec,
        )
    except AIProviderManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_PROVIDER_CONFIGURATION_UPDATED",
        actor=actor,
        detail={
            "provider": body.provider_code,
            "config_id": result.get("id"),
            "version": result.get("config_version"),
            "reason": body.reason,
        },
    )
    return result


@router.patch("/{config_id}")
def patch_config(
    config_id: int,
    body: ConfigUpsertBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    # provider_code는 기존 row에서 결정
    svc = AIProviderManagementService(session)
    try:
        current = svc.get_configuration(config_id)
    except AIProviderManagementError as exc:
        _raise(exc)
        raise
    body.provider_code = current["provider_code"]
    return upsert_config(body=body, request=request, session=session, user=user)


@router.post("/{config_id}/credentials")
def store_credentials(
    config_id: int,
    body: CredentialStoreBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, scope=f"ai-cred-write:{user.user_id}", limit=20, window_seconds=60
    )
    actor = admin_actor_label(user)
    try:
        result = AIProviderManagementService(session).store_credential(
            config_id,
            api_key=body.api_key,
            custom_headers=body.custom_headers,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
            activate=False,
        )
    except AIProviderManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_PROVIDER_CREDENTIAL_STORED",
        actor=actor,
        detail={
            "config_id": config_id,
            "fingerprint_prefix": (result.get("credential") or {}).get(
                "fingerprint_prefix"
            ),
            "reason": body.reason,
            "auto_enabled": False,
            "auto_verified": False,
        },
    )
    # Secret 미포함 보장
    return sanitize_for_log(result)


@router.post("/{config_id}/credentials/verify")
async def verify_credentials(
    config_id: int,
    body: CredentialVerifyBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    enforce_rate_limit(
        request, scope=f"ai-cred-verify:{user.user_id}", limit=10, window_seconds=60
    )
    actor = admin_actor_label(user)
    corr = body.correlation_id or str(uuid4())
    _audit(
        session,
        event_type="AI_PROVIDER_CREDENTIAL_VERIFY_REQUESTED",
        actor=actor,
        detail={"config_id": config_id, "correlation_id": corr},
    )
    try:
        result = await verify_credential(
            session,
            config_id=config_id,
            credential_id=body.credential_id,
            actor=actor,
            reason=body.reason,
            correlation_id=corr,
        )
    except AIProviderManagementError as exc:
        _audit(
            session,
            event_type="AI_PROVIDER_CREDENTIAL_INVALID",
            actor=actor,
            detail={"config_id": config_id, "code": exc.code},
        )
        _raise(exc)
        raise
    _audit(
        session,
        event_type=(
            "AI_PROVIDER_CREDENTIAL_VERIFIED"
            if result.get("ok")
            else "AI_PROVIDER_CREDENTIAL_INVALID"
        ),
        actor=actor,
        detail={
            "config_id": config_id,
            "status": result.get("status"),
            "external_call": result.get("external_call"),
            "correlation_id": corr,
        },
    )
    return sanitize_for_log(result)


@router.post("/{config_id}/credentials/rotate")
async def rotate_credentials(
    config_id: int,
    body: CredentialStoreBody,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """새 Credential 저장 → verify → 성공 시 active switch. 실패 시 기존 유지."""

    enforce_rate_limit(
        request, scope=f"ai-cred-rotate:{user.user_id}", limit=10, window_seconds=60
    )
    actor = admin_actor_label(user)
    corr = body.correlation_id or str(uuid4())
    svc = AIProviderManagementService(session)
    try:
        stored = svc.store_credential(
            config_id,
            api_key=body.api_key,
            custom_headers=body.custom_headers,
            actor=actor,
            reason=body.reason,
            correlation_id=corr,
            activate=False,
        )
    except AIProviderManagementError as exc:
        _raise(exc)
        raise
    new_id = (stored.get("credential") or {}).get("id")
    result = await verify_credential(
        session,
        config_id=config_id,
        credential_id=new_id,
        actor=actor,
        reason=body.reason,
        correlation_id=corr,
    )
    _audit(
        session,
        event_type=(
            "AI_PROVIDER_CREDENTIAL_ROTATED"
            if result.get("ok")
            else "AI_PROVIDER_CREDENTIAL_INVALID"
        ),
        actor=actor,
        detail={
            "config_id": config_id,
            "ok": result.get("ok"),
            "correlation_id": corr,
        },
    )
    return sanitize_for_log(
        {
            "stored": stored,
            "verify": result,
            "previous_kept_on_failure": not bool(result.get("ok")),
        }
    )


@router.post("/{config_id}/credentials/revoke")
def revoke_credentials(
    config_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIProviderManagementService(session).revoke_active_credential(
            config_id,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
    except AIProviderManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_PROVIDER_CREDENTIAL_REVOKED",
        actor=actor,
        detail={"config_id": config_id, "reason": body.reason},
    )
    return sanitize_for_log(result)


@router.post("/{config_id}/enable")
def enable_provider(
    config_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    _audit(
        session,
        event_type="AI_PROVIDER_ENABLE_REQUESTED",
        actor=actor,
        detail={"config_id": config_id, "confirm": body.confirm},
    )
    try:
        result = AIProviderManagementService(session).enable_provider(
            config_id,
            actor=actor,
            reason=body.reason,
            confirm=body.confirm,
            correlation_id=body.correlation_id,
        )
    except AIProviderManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_PROVIDER_ENABLED",
        actor=actor,
        detail={
            "config_id": config_id,
            "auto_test_called": False,
            "reason": body.reason,
        },
    )
    return result


@router.post("/{config_id}/disable")
def disable_provider(
    config_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIProviderManagementService(session).disable_provider(
            config_id,
            actor=actor,
            reason=body.reason,
            correlation_id=body.correlation_id,
        )
    except AIProviderManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_PROVIDER_DISABLED",
        actor=actor,
        detail={"config_id": config_id, "reason": body.reason},
    )
    return result


@router.post("/{config_id}/set-default")
def set_default(
    config_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    actor = admin_actor_label(user)
    try:
        result = AIProviderManagementService(session).set_default(
            config_id,
            actor=actor,
            reason=body.reason,
            confirm=body.confirm,
            correlation_id=body.correlation_id,
        )
    except AIProviderManagementError as exc:
        _raise(exc)
        raise
    _audit(
        session,
        event_type="AI_PROVIDER_DEFAULT_CHANGED",
        actor=actor,
        detail={"config_id": config_id, "reason": body.reason},
    )
    return result


@router.post("/{config_id}/reload")
def reload_provider(
    config_id: int,
    body: ReasonBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """전체 Registry reload (Provider 단위도 동일 경로)."""

    actor = admin_actor_label(user)
    _audit(
        session,
        event_type="AI_PROVIDER_RELOAD_REQUESTED",
        actor=actor,
        detail={"config_id": config_id, "reason": body.reason},
    )
    result = reload_ai_manager_from_db(session, actor=actor)
    _audit(
        session,
        event_type=(
            "AI_PROVIDER_RELOADED"
            if result.get("ok")
            else "AI_PROVIDER_RELOAD_FAILED"
        ),
        actor=actor,
        detail=result,
    )
    return result


@router.get("/{config_id}/history")
def get_history(
    config_id: int,
    limit: int = 50,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    try:
        items = AIProviderManagementService(session).history(
            config_id, limit=limit
        )
    except AIProviderManagementError as exc:
        _raise(exc)
        raise
    return {"count": len(items), "items": items}
