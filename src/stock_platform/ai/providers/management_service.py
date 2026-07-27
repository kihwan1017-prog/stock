"""STEP 11-3 — AI Provider Configuration & Credential Vault Service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.providers.ai_credential_crypto import (
    VaultCryptoError,
    ai_vault_available,
    decrypt_ai_credential,
    encrypt_ai_credential,
    fingerprint_payload,
    mask_api_key,
)
from stock_platform.ai.providers.config import AIProviderConfig
from stock_platform.ai.providers.endpoint_policy import (
    mask_endpoint,
    validate_provider_endpoint,
)
from stock_platform.ai.providers.management_entities import (
    HEADER_ALLOWLIST,
    HEADER_DENYLIST,
    NO_SECRET_PROVIDERS,
    OPTIONAL_SECRET_PROVIDERS,
    PROVIDER_CODES,
    AIProviderConfigurationEntity,
    AIProviderConfigurationHistoryEntity,
    AIProviderCredentialEntity,
)
from stock_platform.ai.providers.security import sanitize_for_log


class AIProviderManagementError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _public_config(row: AIProviderConfigurationEntity) -> dict[str, Any]:
    return {
        "id": row.provider_configuration_id,
        "provider_code": row.provider_code,
        "display_name": row.display_name,
        "enabled": row.enabled,
        "is_default": row.is_default,
        "priority": row.priority,
        "model": row.model,
        "endpoint": mask_endpoint(row.endpoint),
        "endpoint_raw_set": bool(row.endpoint),
        "timeout_sec": row.timeout_sec,
        "retry_max": row.retry_max,
        "max_tokens": row.max_tokens,
        "temperature": row.temperature,
        "capability_overrides": row.capability_overrides,
        "health_check_enabled": row.health_check_enabled,
        "health_check_interval_sec": row.health_check_interval_sec,
        "config_version": row.config_version,
        "runtime_loaded_version": row.runtime_loaded_version,
        "reload_required": row.reload_required,
        "last_reload_result": row.last_reload_result,
        "last_reload_at": (
            row.last_reload_at.isoformat() if row.last_reload_at else None
        ),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "requires_credential": row.provider_code not in NO_SECRET_PROVIDERS,
        "credential_optional": row.provider_code in OPTIONAL_SECRET_PROVIDERS,
    }


def _public_credential(
    row: AIProviderCredentialEntity | None,
) -> dict[str, Any] | None:
    if row is None:
        return None
    fp = row.fingerprint
    return {
        "id": row.provider_credential_id,
        "status": row.status,
        "is_active": row.is_active,
        "credential_type": row.credential_type,
        "fingerprint_prefix": fp[:8] if fp else None,
        "masked_identifier": row.masked_identifier,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "last_used_at": (
            row.last_used_at.isoformat() if row.last_used_at else None
        ),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "verification_message": row.verification_message,
        # Secret 절대 미포함
    }


def _sanitize_headers(raw: dict[str, Any] | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for key, value in list(raw.items())[:10]:
        key_l = str(key).strip().lower()
        if key_l in HEADER_DENYLIST or key_l == "cookie":
            raise AIProviderManagementError(
                "HEADER_FORBIDDEN",
                f"Header '{key_l}' is not allowed",
            )
        if key_l.startswith("authorization"):
            # Authorization은 api_key로만 저장
            raise AIProviderManagementError(
                "HEADER_FORBIDDEN",
                "Use api_key field for Authorization",
            )
        if key_l not in HEADER_ALLOWLIST:
            raise AIProviderManagementError(
                "HEADER_NOT_ALLOWLISTED",
                f"Header '{key_l}' not in allowlist",
            )
        out[key_l] = str(value)[:256]
    return out


class AIProviderManagementService:
    """설정/Credential CRUD — 자동 enable·자동 AI 호출 없음."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ---- history / audit helpers ----

    def _history(
        self,
        *,
        config_id: int,
        action: str,
        previous: dict[str, Any] | None,
        new: dict[str, Any] | None,
        actor: str,
        reason: str | None,
        correlation_id: str | None,
    ) -> None:
        self._session.add(
            AIProviderConfigurationHistoryEntity(
                provider_configuration_id=config_id,
                action=action,
                previous_value=sanitize_for_log(previous or {}),
                new_value=sanitize_for_log(new or {}),
                changed_by=actor,
                reason=(reason or "")[:500],
                correlation_id=correlation_id,
            )
        )

    def _get_config(self, config_id: int) -> AIProviderConfigurationEntity:
        row = self._session.get(AIProviderConfigurationEntity, config_id)
        if row is None:
            raise AIProviderManagementError("NOT_FOUND", "Configuration not found")
        return row

    def _active_credential(
        self, config_id: int
    ) -> AIProviderCredentialEntity | None:
        return self._session.scalar(
            select(AIProviderCredentialEntity).where(
                AIProviderCredentialEntity.provider_configuration_id
                == config_id,
                AIProviderCredentialEntity.is_active.is_(True),
            )
        )

    def list_configurations(self) -> list[dict[str, Any]]:
        rows = list(
            self._session.scalars(
                select(AIProviderConfigurationEntity).order_by(
                    AIProviderConfigurationEntity.priority,
                    AIProviderConfigurationEntity.provider_code,
                )
            )
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            item = _public_config(row)
            cred = self._active_credential(row.provider_configuration_id)
            item["credential"] = _public_credential(cred)
            item["config_source"] = "DB"
            item["config_drift"] = bool(
                row.reload_required
                or (
                    row.runtime_loaded_version is not None
                    and row.runtime_loaded_version != row.config_version
                )
            )
            items.append(item)
        return items

    def get_configuration(self, config_id: int) -> dict[str, Any]:
        row = self._get_config(config_id)
        item = _public_config(row)
        item["credential"] = _public_credential(
            self._active_credential(config_id)
        )
        item["config_source"] = "DB"
        item["config_drift"] = bool(row.reload_required)
        return item

    def create_or_update_configuration(
        self,
        *,
        provider_code: str,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
        expected_version: int | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        code = provider_code.strip().lower()
        if code not in PROVIDER_CODES:
            raise AIProviderManagementError("INVALID_PROVIDER", "Unknown provider")
        if not reason.strip():
            raise AIProviderManagementError("REASON_REQUIRED", "reason required")

        row = self._session.scalar(
            select(AIProviderConfigurationEntity).where(
                AIProviderConfigurationEntity.provider_code == code
            )
        )
        corr = correlation_id or str(uuid4())
        previous = _public_config(row) if row else None

        if row is None:
            row = AIProviderConfigurationEntity(
                provider_code=code,
                display_name=str(fields.get("display_name") or code),
                created_by=actor,
                updated_by=actor,
            )
            self._session.add(row)
            action = "AI_PROVIDER_CONFIGURATION_CREATED"
        else:
            if (
                expected_version is not None
                and row.config_version != expected_version
            ):
                raise AIProviderManagementError(
                    "VERSION_CONFLICT",
                    "Optimistic lock conflict",
                )
            action = "AI_PROVIDER_CONFIGURATION_UPDATED"

        # enable/default은 이 메서드에서 바꾸지 않음
        if "display_name" in fields and fields["display_name"]:
            row.display_name = str(fields["display_name"])[:100]
        if "model" in fields and fields["model"] is not None:
            row.model = str(fields["model"])[:200]
        if "endpoint" in fields and fields["endpoint"] is not None:
            endpoint = str(fields["endpoint"]).strip()
            if endpoint:
                allow_local = code in {"ollama", "openai_compatible", "mock"}
                validate_provider_endpoint(
                    endpoint,
                    allow_localhost=allow_local,
                    provider_id=code,
                )
            row.endpoint = endpoint[:500]
        if "priority" in fields and fields["priority"] is not None:
            row.priority = int(fields["priority"])
        if "timeout_sec" in fields and fields["timeout_sec"] is not None:
            timeout = float(fields["timeout_sec"])
            if timeout < 1 or timeout > 600:
                raise AIProviderManagementError(
                    "INVALID_TIMEOUT", "timeout_sec out of range"
                )
            row.timeout_sec = timeout
        if "retry_max" in fields and fields["retry_max"] is not None:
            retry = int(fields["retry_max"])
            if retry < 0 or retry > 10:
                raise AIProviderManagementError(
                    "INVALID_RETRY", "retry_max out of range"
                )
            row.retry_max = retry
        if "max_tokens" in fields and fields["max_tokens"] is not None:
            mt = int(fields["max_tokens"])
            if mt < 1 or mt > 128000:
                raise AIProviderManagementError(
                    "INVALID_MAX_TOKENS", "max_tokens out of range"
                )
            row.max_tokens = mt
        if "temperature" in fields and fields["temperature"] is not None:
            temp = float(fields["temperature"])
            if temp < 0 or temp > 2:
                raise AIProviderManagementError(
                    "INVALID_TEMPERATURE", "temperature out of range"
                )
            row.temperature = temp
        if "health_check_enabled" in fields:
            row.health_check_enabled = bool(fields["health_check_enabled"])
        if "health_check_interval_sec" in fields:
            row.health_check_interval_sec = int(
                fields["health_check_interval_sec"]
            )

        if action.endswith("CREATED"):
            row.config_version = 1
        else:
            row.config_version = int(row.config_version or 1) + 1
        row.reload_required = True
        row.updated_by = actor
        row.updated_at = _now()
        self._session.flush()

        self._history(
            config_id=row.provider_configuration_id,
            action=action,
            previous=previous,
            new=_public_config(row),
            actor=actor,
            reason=reason,
            correlation_id=corr,
        )
        self._session.commit()
        return self.get_configuration(row.provider_configuration_id)

    def store_credential(
        self,
        config_id: int,
        *,
        api_key: str | None,
        custom_headers: dict[str, Any] | None,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
        activate: bool = False,
    ) -> dict[str, Any]:
        """새 Credential 저장 — 기본 PENDING, 자동 active/verify 없음.

        activate=False: rotation 준비용 PENDING row
        activate는 rotate 성공 경로에서만 True
        """

        if not reason.strip():
            raise AIProviderManagementError("REASON_REQUIRED", "reason required")
        row = self._get_config(config_id)
        if row.provider_code in NO_SECRET_PROVIDERS:
            raise AIProviderManagementError(
                "SECRET_NOT_REQUIRED",
                "This provider does not use credentials",
            )
        if not ai_vault_available():
            raise AIProviderManagementError(
                "MASTER_KEY_MISSING",
                "Vault master key missing (Fail Closed)",
            )

        payload: dict[str, Any] = {}
        key = (api_key or "").strip()
        if key:
            payload["api_key"] = key
        headers = _sanitize_headers(custom_headers)
        if headers:
            payload["headers"] = headers
        if not payload:
            if row.provider_code not in OPTIONAL_SECRET_PROVIDERS:
                raise AIProviderManagementError(
                    "EMPTY_CREDENTIAL",
                    "api_key required",
                )
            payload = {"api_key": ""}

        try:
            blob = encrypt_ai_credential(payload)
        except VaultCryptoError as exc:
            raise AIProviderManagementError(
                "ENCRYPT_FAILED", str(exc)
            ) from exc

        fp = fingerprint_payload(payload)
        cred = AIProviderCredentialEntity(
            provider_configuration_id=config_id,
            credential_type=(
                "API_KEY_OPTIONAL"
                if row.provider_code in OPTIONAL_SECRET_PROVIDERS
                else "API_KEY"
            ),
            encrypted_payload=blob.ciphertext_b64,
            nonce_b64=blob.nonce_b64,
            encryption_algorithm=blob.algorithm,
            key_version=blob.key_version,
            status="PENDING",
            is_active=False,
            fingerprint=fp,
            masked_identifier=mask_api_key(key) if key else None,
            created_by=actor,
            updated_by=actor,
        )
        self._session.add(cred)
        self._session.flush()

        if activate:
            # 기존 active 해제 후 활성화 (rotate 경로)
            current = self._active_credential(config_id)
            if current is not None:
                current.is_active = False
                current.status = "REVOKED"
                current.revoked_at = _now()
            cred.is_active = True

        row.reload_required = True
        row.config_version = int(row.config_version) + 1
        row.updated_by = actor
        corr = correlation_id or str(uuid4())
        self._history(
            config_id=config_id,
            action="AI_PROVIDER_CREDENTIAL_STORED",
            previous=None,
            new={
                "credential_id": cred.provider_credential_id,
                "fingerprint_prefix": fp[:8],
                "status": cred.status,
                "is_active": cred.is_active,
            },
            actor=actor,
            reason=reason,
            correlation_id=corr,
        )
        self._session.commit()
        return {
            "configuration": self.get_configuration(config_id),
            "credential": _public_credential(cred),
            "correlation_id": corr,
        }

    def resolve_active_secret(
        self, config_id: int
    ) -> dict[str, Any] | None:
        """Runtime용 복호화 — 응답/로그에 사용 금지."""

        cred = self._active_credential(config_id)
        if cred is None:
            return None
        # Runtime 복호화는 VERIFIED만 (PENDING은 verify 전)
        if cred.status != "VERIFIED":
            return None
        try:
            payload = decrypt_ai_credential(
                ciphertext_b64=cred.encrypted_payload,
                nonce_b64=cred.nonce_b64,
                key_version=cred.key_version,
                algorithm=cred.encryption_algorithm,
            )
        except VaultCryptoError:
            return None
        cred.last_used_at = _now()
        return payload

    def mark_credential_status(
        self,
        credential_id: int,
        *,
        status: str,
        message: str | None,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
        activate_if_verified: bool = False,
    ) -> dict[str, Any]:
        cred = self._session.get(AIProviderCredentialEntity, credential_id)
        if cred is None:
            raise AIProviderManagementError("NOT_FOUND", "Credential not found")
        previous = _public_credential(cred)
        cred.status = status
        cred.verification_message = (message or "")[:500]
        cred.updated_by = actor
        if status == "VERIFIED":
            cred.verified_at = _now()
            if activate_if_verified:
                active = self._active_credential(cred.provider_configuration_id)
                if active and active.provider_credential_id != credential_id:
                    active.is_active = False
                    active.status = "REVOKED"
                    active.revoked_at = _now()
                cred.is_active = True
        if status == "REVOKED":
            cred.is_active = False
            cred.revoked_at = _now()
        if status == "INVALID":
            # 실패 시 기존 active 유지 — 이 row만 INVALID
            pass
        self._history(
            config_id=cred.provider_configuration_id,
            action=f"AI_PROVIDER_CREDENTIAL_{status}",
            previous=previous,
            new=_public_credential(cred),
            actor=actor,
            reason=reason,
            correlation_id=correlation_id or str(uuid4()),
        )
        self._session.commit()
        return _public_credential(cred) or {}

    def revoke_active_credential(
        self,
        config_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise AIProviderManagementError("REASON_REQUIRED", "reason required")
        row = self._get_config(config_id)
        if row.provider_code == "mock":
            raise AIProviderManagementError(
                "MOCK_IMMUTABLE", "Mock credentials not applicable"
            )
        cred = self._active_credential(config_id)
        if cred is None:
            raise AIProviderManagementError("NOT_FOUND", "No active credential")
        if row.enabled and row.provider_code not in NO_SECRET_PROVIDERS:
            # enable 상태면 먼저 disable 권장 — 강제 revoke 시 disable
            row.enabled = False
            row.is_default = False
        previous = _public_credential(cred)
        cred.is_active = False
        cred.status = "REVOKED"
        cred.revoked_at = _now()
        cred.updated_by = actor
        row.reload_required = True
        row.config_version = int(row.config_version) + 1
        corr = correlation_id or str(uuid4())
        self._history(
            config_id=config_id,
            action="AI_PROVIDER_CREDENTIAL_REVOKED",
            previous=previous,
            new=_public_credential(cred),
            actor=actor,
            reason=reason,
            correlation_id=corr,
        )
        self._session.commit()
        return {
            "configuration": self.get_configuration(config_id),
            "credential": _public_credential(cred),
            "correlation_id": corr,
        }

    def enable_provider(
        self,
        config_id: int,
        *,
        actor: str,
        reason: str,
        confirm: bool,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not confirm:
            raise AIProviderManagementError(
                "CONFIRM_REQUIRED",
                "confirm=true required for enable",
            )
        if not reason.strip():
            raise AIProviderManagementError("REASON_REQUIRED", "reason required")
        row = self._get_config(config_id)
        previous = _public_config(row)

        # Credential 조건
        if row.provider_code not in NO_SECRET_PROVIDERS:
            if row.provider_code in OPTIONAL_SECRET_PROVIDERS:
                # optional: credential 없으면 OK, 있으면 VERIFIED 필수
                cred = self._active_credential(config_id)
                if cred is not None and cred.status != "VERIFIED":
                    raise AIProviderManagementError(
                        "CREDENTIAL_NOT_VERIFIED",
                        "Active credential must be VERIFIED",
                    )
            else:
                cred = self._active_credential(config_id)
                if cred is None or cred.status != "VERIFIED":
                    raise AIProviderManagementError(
                        "CREDENTIAL_NOT_VERIFIED",
                        "VERIFIED credential required before enable",
                    )
                if not ai_vault_available():
                    raise AIProviderManagementError(
                        "MASTER_KEY_MISSING",
                        "Vault master key required",
                    )

        if row.endpoint:
            allow_local = row.provider_code in {
                "ollama",
                "openai_compatible",
                "mock",
            }
            try:
                validate_provider_endpoint(
                    row.endpoint,
                    allow_localhost=allow_local,
                    provider_id=row.provider_code,
                )
            except Exception as exc:  # noqa: BLE001
                raise AIProviderManagementError(
                    "INVALID_ENDPOINT", str(exc)
                ) from exc
        if not row.model and row.provider_code != "mock":
            raise AIProviderManagementError("MODEL_REQUIRED", "model required")

        row.enabled = True
        row.reload_required = True
        row.config_version = int(row.config_version) + 1
        row.updated_by = actor
        corr = correlation_id or str(uuid4())
        self._history(
            config_id=config_id,
            action="AI_PROVIDER_ENABLED",
            previous=previous,
            new=_public_config(row),
            actor=actor,
            reason=reason,
            correlation_id=corr,
        )
        self._session.commit()
        return {
            "configuration": self.get_configuration(config_id),
            "correlation_id": corr,
            "auto_test_called": False,
        }

    def disable_provider(
        self,
        config_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise AIProviderManagementError("REASON_REQUIRED", "reason required")
        row = self._get_config(config_id)
        if row.provider_code == "mock" and row.is_default:
            # Mock은 disable 가능하지만 default 해제 필요 — 다른 default 없으면 경고
            pass
        previous = _public_config(row)
        row.enabled = False
        if row.is_default:
            row.is_default = False
        row.reload_required = True
        row.config_version = int(row.config_version) + 1
        row.updated_by = actor
        corr = correlation_id or str(uuid4())
        self._history(
            config_id=config_id,
            action="AI_PROVIDER_DISABLED",
            previous=previous,
            new=_public_config(row),
            actor=actor,
            reason=reason,
            correlation_id=corr,
        )
        self._session.commit()
        return {
            "configuration": self.get_configuration(config_id),
            "correlation_id": corr,
        }

    def set_default(
        self,
        config_id: int,
        *,
        actor: str,
        reason: str,
        confirm: bool,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not confirm:
            raise AIProviderManagementError(
                "CONFIRM_REQUIRED", "confirm=true required"
            )
        if not reason.strip():
            raise AIProviderManagementError("REASON_REQUIRED", "reason required")
        row = self._get_config(config_id)
        if not row.enabled:
            raise AIProviderManagementError(
                "DEFAULT_REQUIRES_ENABLED",
                "disabled provider cannot be default",
            )
        # 기존 default 해제
        others = list(
            self._session.scalars(
                select(AIProviderConfigurationEntity).where(
                    AIProviderConfigurationEntity.is_default.is_(True)
                )
            )
        )
        for other in others:
            if other.provider_configuration_id != config_id:
                other.is_default = False
                other.config_version = int(other.config_version) + 1
                other.reload_required = True
        previous = _public_config(row)
        row.is_default = True
        row.reload_required = True
        row.config_version = int(row.config_version) + 1
        row.updated_by = actor
        corr = correlation_id or str(uuid4())
        self._history(
            config_id=config_id,
            action="AI_PROVIDER_DEFAULT_CHANGED",
            previous=previous,
            new=_public_config(row),
            actor=actor,
            reason=reason,
            correlation_id=corr,
        )
        self._session.commit()
        return {
            "configuration": self.get_configuration(config_id),
            "correlation_id": corr,
        }

    def mark_reloaded(
        self,
        *,
        success: bool,
        loaded_versions: dict[str, int],
        actor: str,
        correlation_id: str | None = None,
        write_history: bool = True,
    ) -> None:
        rows = list(self._session.scalars(select(AIProviderConfigurationEntity)))
        for row in rows:
            ver = loaded_versions.get(row.provider_code)
            if ver is not None:
                row.runtime_loaded_version = ver
                row.reload_required = row.config_version != ver
            row.last_reload_result = "OK" if success else "FAILED"
            row.last_reload_at = _now()
            if write_history:
                self._history(
                    config_id=row.provider_configuration_id,
                    action=(
                        "AI_PROVIDER_RELOADED"
                        if success
                        else "AI_PROVIDER_RELOAD_FAILED"
                    ),
                    previous=None,
                    new={
                        "runtime_loaded_version": row.runtime_loaded_version,
                        "config_version": row.config_version,
                        "reload_required": row.reload_required,
                    },
                    actor=actor,
                    reason="registry reload",
                    correlation_id=correlation_id or str(uuid4()),
                )
        self._session.commit()

    def history(
        self, config_id: int, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        self._get_config(config_id)
        rows = list(
            self._session.scalars(
                select(AIProviderConfigurationHistoryEntity)
                .where(
                    AIProviderConfigurationHistoryEntity.provider_configuration_id
                    == config_id
                )
                .order_by(
                    AIProviderConfigurationHistoryEntity.provider_configuration_history_id.desc()
                )
                .limit(max(1, min(limit, 200)))
            )
        )
        return [
            {
                "id": r.provider_configuration_history_id,
                "action": r.action,
                "previous_value": r.previous_value,
                "new_value": r.new_value,
                "changed_by": r.changed_by,
                "reason": r.reason,
                "correlation_id": r.correlation_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    def to_runtime_configs(self) -> list[AIProviderConfig]:
        """DB → AIProviderConfig (Secret은 복호화해 api_key에만)."""

        rows = list(self._session.scalars(select(AIProviderConfigurationEntity)))
        configs: list[AIProviderConfig] = []
        for row in rows:
            api_key = ""
            extra: dict[str, Any] = {}
            if row.provider_code not in NO_SECRET_PROVIDERS:
                secret = self.resolve_active_secret(row.provider_configuration_id)
                if secret:
                    api_key = str(secret.get("api_key") or "")
                    headers = secret.get("headers")
                    if isinstance(headers, dict):
                        extra["headers"] = headers
            if row.provider_code == "mock":
                extra.setdefault("fixed_signal", "HOLD")
                extra.setdefault("latency_ms", 5.0)
            configs.append(
                AIProviderConfig(
                    provider_id=row.provider_code,
                    enabled=bool(row.enabled),
                    priority=int(row.priority),
                    is_default=bool(row.is_default),
                    model=row.model,
                    api_endpoint=row.endpoint,
                    api_key=api_key,
                    timeout_seconds=float(row.timeout_sec),
                    retry_max=int(row.retry_max),
                    max_tokens=int(row.max_tokens),
                    temperature=float(row.temperature),
                    extra=extra,
                )
            )
        return configs
