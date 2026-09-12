"""STEP 8-5-2 — USER Broker Credential Vault API.

Secret 원문은 응답·로그에 포함하지 않는다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import AuditLogService, get_audit_service
from stock_platform.auth.account_ownership import assert_broker_account_access
from stock_platform.auth.deps import AuthenticatedUser, require_permission
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
    BrokerCredentialVaultService,
)
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/user/accounts",
    tags=["User Broker Credentials"],
)


class CredentialUpsertRequest(BaseModel):
    """Broker별 필드를 한 모델로 받되, 검증은 서비스에서 수행."""

    app_key: str | None = Field(default=None, max_length=200)
    secret_key: str | None = Field(default=None, max_length=200)
    account_number: str | None = Field(default=None, max_length=64)
    account_product_code: str | None = Field(default=None, max_length=20)
    is_mock: bool | None = None
    access_key: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _require_some_secret(self) -> "CredentialUpsertRequest":
        # 값 자체는 에러 메시지에 넣지 않음
        has_kiwoom = bool(
            self.app_key and self.secret_key and self.account_number
        )
        has_upbit = bool(self.access_key and self.secret_key)
        if not has_kiwoom and not has_upbit:
            raise ValueError("Credential fields incomplete for broker")
        # Kiwoom은 REAL/MOCK을 명시 — global settings 암묵 의존 금지
        if has_kiwoom and self.is_mock is None:
            raise ValueError("is_mock is required for Kiwoom credentials")
        return self

    def as_payload(self) -> dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        # user_id 등 위조 필드 차단 — 모델에 없음
        return data


def _http(exc: BrokerCredentialVaultError) -> HTTPException:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code in {
        "credential_ownership_denied",
    }:
        code = status.HTTP_403_FORBIDDEN
    elif exc.code in {
        "credential_missing",
    }:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code == "vault_unavailable":
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HTTPException(
        status_code=code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.get("/{uba_id}/credentials/status")
def get_credential_status(
    uba_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    assert_broker_account_access(user, uba_id, session)
    view = BrokerCredentialVaultService(session).status(uba_id)
    return view.as_dict()


@router.post("/{uba_id}/credentials", status_code=status.HTTP_201_CREATED)
def register_credential(
    uba_id: int,
    body: CredentialUpsertRequest,
    request: Request,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    assert_broker_account_access(user, uba_id, session)
    service = BrokerCredentialVaultService(session)
    before = service.status(uba_id)
    try:
        after = service.upsert(
            user_broker_account_id=uba_id,
            owner_user_id=int(user.user_id),
            plaintext=body.as_payload(),
            actor=f"user:{user.user_id}",
            replace=False,
        )
    except BrokerCredentialVaultError as exc:
        raise _http(exc) from exc

    audit.record(
        event_type="BROKER_CREDENTIAL_REGISTER",
        actor=f"user:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "user_broker_account_id": uba_id,
            "before_status": before.verification_status,
            "after_status": after.verification_status,
            "key_version": after.key_version,
            "connected": after.connected,
        },
    )
    return after.as_dict()


@router.put("/{uba_id}/credentials")
def replace_credential(
    uba_id: int,
    body: CredentialUpsertRequest,
    request: Request,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    assert_broker_account_access(user, uba_id, session)
    service = BrokerCredentialVaultService(session)
    before = service.status(uba_id)
    try:
        after = service.upsert(
            user_broker_account_id=uba_id,
            owner_user_id=int(user.user_id),
            plaintext=body.as_payload(),
            actor=f"user:{user.user_id}",
            replace=True,
        )
    except BrokerCredentialVaultError as exc:
        raise _http(exc) from exc

    audit.record(
        event_type="BROKER_CREDENTIAL_REPLACE",
        actor=f"user:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "user_broker_account_id": uba_id,
            "before_status": before.verification_status,
            "after_status": after.verification_status,
            "key_version": after.key_version,
        },
    )
    return after.as_dict()


@router.delete("/{uba_id}/credentials")
def revoke_credential(
    uba_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    assert_broker_account_access(user, uba_id, session)
    service = BrokerCredentialVaultService(session)
    before = service.status(uba_id)
    try:
        after = service.revoke(
            user_broker_account_id=uba_id,
            owner_user_id=int(user.user_id),
            actor=f"user:{user.user_id}",
        )
    except BrokerCredentialVaultError as exc:
        raise _http(exc) from exc

    audit.record(
        event_type="BROKER_CREDENTIAL_REVOKE",
        actor=f"user:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "user_broker_account_id": uba_id,
            "before_status": before.verification_status,
            "after_status": after.verification_status,
        },
    )
    return after.as_dict()


@router.post("/{uba_id}/credentials/verify")
def verify_credential(
    uba_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    assert_broker_account_access(user, uba_id, session)
    service = BrokerCredentialVaultService(session)
    before = service.status(uba_id)
    try:
        after = service.verify(
            user_broker_account_id=uba_id,
            owner_user_id=int(user.user_id),
            actor=f"user:{user.user_id}",
        )
    except BrokerCredentialVaultError as exc:
        audit.record(
            event_type="BROKER_CREDENTIAL_VERIFY_FAILED",
            actor=f"user:{user.user_id}",
            request_id=getattr(request.state, "request_id", None),
            detail={
                "user_broker_account_id": uba_id,
                "code": exc.code,
                "before_status": before.verification_status,
            },
        )
        raise _http(exc) from exc

    audit.record(
        event_type="BROKER_CREDENTIAL_VERIFY",
        actor=f"user:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "user_broker_account_id": uba_id,
            "before_status": before.verification_status,
            "after_status": after.verification_status,
            "key_version": after.key_version,
        },
    )
    return after.as_dict()
