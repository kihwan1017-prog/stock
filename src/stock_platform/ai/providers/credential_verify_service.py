"""STEP 11-3 — Credential Verify (명시적·저비용, 기본 테스트는 Mock HTTP)."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.orm import Session

from stock_platform.ai.providers.ai_credential_crypto import (
    decrypt_ai_credential,
)
from stock_platform.ai.providers.claude_provider import ClaudeProvider
from stock_platform.ai.providers.config import AIProviderConfig
from stock_platform.ai.providers.dto import AIChatRequest, ChatMessage
from stock_platform.ai.providers.gemini_provider import GeminiProvider
from stock_platform.ai.providers.management_entities import (
    NO_SECRET_PROVIDERS,
    AIProviderCredentialEntity,
)
from stock_platform.ai.providers.management_service import (
    AIProviderManagementError,
    AIProviderManagementService,
)
from stock_platform.ai.providers.ollama_provider import OllamaProvider
from stock_platform.ai.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
)
from stock_platform.ai.providers.openai_provider import OpenAIProvider


async def verify_credential(
    session: Session,
    *,
    config_id: int,
    credential_id: int | None = None,
    actor: str,
    reason: str,
    http_client: httpx.AsyncClient | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """운영자 명시 검증 — 저장만으로 자동 호출되지 않음."""

    svc = AIProviderManagementService(session)
    config = svc.get_configuration(config_id)
    code = config["provider_code"]

    if code in NO_SECRET_PROVIDERS:
        return {
            "ok": True,
            "provider": code,
            "status": "VERIFIED",
            "message": "No credential required",
            "external_call": False,
            "estimated_cost": None,
        }

    cred: AIProviderCredentialEntity | None
    if credential_id is not None:
        cred = session.get(AIProviderCredentialEntity, credential_id)
    else:
        # 최신 PENDING 우선, 없으면 active
        from sqlalchemy import select

        cred = session.scalar(
            select(AIProviderCredentialEntity)
            .where(
                AIProviderCredentialEntity.provider_configuration_id
                == config_id,
                AIProviderCredentialEntity.status == "PENDING",
            )
            .order_by(
                AIProviderCredentialEntity.provider_credential_id.desc()
            )
            .limit(1)
        ) or session.scalar(
            select(AIProviderCredentialEntity).where(
                AIProviderCredentialEntity.provider_configuration_id
                == config_id,
                AIProviderCredentialEntity.is_active.is_(True),
            )
        )
    if cred is None:
        raise AIProviderManagementError("NOT_FOUND", "Credential not found")

    try:
        secret = decrypt_ai_credential(
            ciphertext_b64=cred.encrypted_payload,
            nonce_b64=cred.nonce_b64,
            key_version=cred.key_version,
            algorithm=cred.encryption_algorithm,
        )
    except Exception as exc:  # noqa: BLE001
        svc.mark_credential_status(
            cred.provider_credential_id,
            status="INVALID",
            message="decrypt failed",
            actor=actor,
            reason=reason,
            correlation_id=correlation_id,
        )
        raise AIProviderManagementError(
            "DECRYPT_FAILED", "Credential decrypt failed"
        ) from exc

    api_key = str(secret.get("api_key") or "")
    headers = secret.get("headers") if isinstance(secret.get("headers"), dict) else {}
    # endpoint는 public_config에 masked만 — DB row에서 재조회
    from stock_platform.ai.providers.management_entities import (
        AIProviderConfigurationEntity,
    )

    row = session.get(AIProviderConfigurationEntity, config_id)
    assert row is not None
    cfg = AIProviderConfig(
        provider_id=code,
        enabled=True,
        model=row.model,
        api_endpoint=row.endpoint,
        api_key=api_key,
        timeout_seconds=min(float(row.timeout_sec), 30.0),
        max_tokens=8,
        temperature=0.0,
        extra={"headers": headers} if headers else {},
    )

    external_call = True
    ok = False
    message = ""
    latency_ms = None
    try:
        if code == "openai":
            provider = OpenAIProvider(cfg, http_client=http_client)
            health = await provider.health()
            ok = health.status.value == "HEALTHY"
            message = health.message or health.status.value
            latency_ms = health.latency_ms
        elif code == "gemini":
            provider = GeminiProvider(cfg, http_client=http_client)
            health = await provider.health()
            ok = health.status.value == "HEALTHY"
            message = health.message or health.status.value
            latency_ms = health.latency_ms
        elif code == "ollama":
            provider = OllamaProvider(cfg, http_client=http_client)
            health = await provider.health()
            ok = health.status.value == "HEALTHY"
            message = health.message or health.status.value
            latency_ms = health.latency_ms
        elif code == "openai_compatible":
            provider = OpenAICompatibleProvider(cfg, http_client=http_client)
            health = await provider.health()
            ok = health.status.value == "HEALTHY"
            message = health.message or health.status.value
            latency_ms = health.latency_ms
        elif code == "claude":
            # 저비용 list 없음 → 최소 chat
            provider = ClaudeProvider(cfg, http_client=http_client)
            response = await provider.chat(
                AIChatRequest(
                    messages=[
                        ChatMessage(role="user", content="Return exactly: OK")
                    ],
                    max_tokens=8,
                )
            )
            ok = response.ok
            message = (
                "chat probe OK"
                if response.ok
                else (response.error.code if response.error else "ERROR")
            )
            latency_ms = response.latency_ms
        else:
            external_call = False
            ok = False
            message = "unsupported provider"
    except Exception as exc:  # noqa: BLE001
        ok = False
        message = type(exc).__name__

    status = "VERIFIED" if ok else "INVALID"
    public = svc.mark_credential_status(
        cred.provider_credential_id,
        status=status,
        message=message,
        actor=actor,
        reason=reason,
        correlation_id=correlation_id,
        activate_if_verified=ok,
    )
    return {
        "ok": ok,
        "provider": code,
        "status": status,
        "message": message,
        "latency_ms": latency_ms,
        "external_call": external_call,
        "estimated_cost": None,
        "credential": public,
    }
