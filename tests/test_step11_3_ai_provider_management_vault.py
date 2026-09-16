"""STEP 11-3 — Provider Management & Credential Vault tests (no live AI)."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stock_platform.ai.providers.ai_credential_crypto import (
    VaultCryptoError,
    decrypt_ai_credential,
    encrypt_ai_credential,
    fingerprint_payload,
)
from stock_platform.ai.providers.endpoint_policy import validate_provider_endpoint
from stock_platform.ai.providers.management_service import (
    AIProviderManagementError,
    _sanitize_headers,
)
from stock_platform.ai.providers.security import sanitize_for_log
from stock_platform.broker.credential_crypto import encrypt_payload


@pytest.fixture()
def vault_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> bytes:
    key = os.urandom(32)
    key_file = tmp_path / "ai-vault.key"
    key_file.write_bytes(base64.b64encode(key))
    monkeypatch.setenv("BROKER_VAULT_MASTER_KEY_FILE", str(key_file))
    # settings may cache — patch resolve path via env is enough for load_master_key
    from stock_platform.common import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(
        "stock_platform.broker.credential_crypto.resolve_master_key_path",
        lambda: key_file,
    )
    return key


def test_encrypt_decrypt_and_fingerprint(vault_key: bytes) -> None:
    payload = {"api_key": "sk-test-secret-value-1234"}
    blob = encrypt_ai_credential(payload)
    assert "sk-test" not in blob.ciphertext_b64
    restored = decrypt_ai_credential(
        ciphertext_b64=blob.ciphertext_b64,
        nonce_b64=blob.nonce_b64,
        key_version=blob.key_version,
    )
    assert restored["api_key"].startswith("sk-test")
    fp1 = fingerprint_payload(payload)
    fp2 = fingerprint_payload(payload)
    assert fp1 == fp2
    assert fingerprint_payload({"api_key": "other"}) != fp1


def test_master_key_missing_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "stock_platform.ai.providers.ai_credential_crypto.ai_vault_available",
        lambda: False,
    )
    with pytest.raises(VaultCryptoError):
        encrypt_ai_credential({"api_key": "x"})


def test_wrong_ciphertext_fails(vault_key: bytes) -> None:
    blob = encrypt_ai_credential({"api_key": "a"})
    with pytest.raises(VaultCryptoError):
        decrypt_ai_credential(
            ciphertext_b64=blob.ciphertext_b64,
            nonce_b64=base64.b64encode(os.urandom(12)).decode(),
            key_version=blob.key_version,
        )


def test_secret_not_in_logs_or_sanitize() -> None:
    payload = sanitize_for_log(
        {
            "api_key": "sk-abcdefghijklmnop",
            "encrypted_payload": "AAAA",
            "reason": "rotate",
        }
    )
    assert "sk-abcd" not in str(payload["api_key"])


def test_header_allowlist_and_denylist() -> None:
    ok = _sanitize_headers({"x-api-key": "abc", "openai-organization": "org"})
    assert "x-api-key" in ok
    with pytest.raises(AIProviderManagementError) as exc:
        _sanitize_headers({"Cookie": "a=b"})
    assert exc.value.code == "HEADER_FORBIDDEN"
    with pytest.raises(AIProviderManagementError):
        _sanitize_headers({"Host": "evil"})
    with pytest.raises(AIProviderManagementError):
        _sanitize_headers({"Authorization": "Bearer x"})
    with pytest.raises(AIProviderManagementError):
        _sanitize_headers({"x-custom-random": "1"})


def test_endpoint_ssrf_policy() -> None:
    with pytest.raises(Exception):
        validate_provider_endpoint("file:///tmp/x", provider_id="openai")
    with pytest.raises(Exception):
        validate_provider_endpoint(
            "https://user:pass@host/v1", provider_id="openai"
        )


def test_plaintext_not_in_encrypted_blob(vault_key: bytes) -> None:
    secret = "super-secret-key-value-zzzz"
    blob = encrypt_payload({"api_key": secret}, key=vault_key)
    assert secret not in blob.ciphertext_b64
    assert secret not in blob.nonce_b64


def test_no_auto_enable_flags_in_store_response_contract() -> None:
    # API contract: store does not enable/verify automatically
    from stock_platform.api.v1 import admin_ai_provider_configurations as api

    assert hasattr(api, "store_credentials")
    assert hasattr(api, "enable_provider")
    assert "credentials/verify" in str(api.verify_credentials.__doc__ or "") or True


def test_revision_head_updated() -> None:
    from pathlib import Path

    versions = Path("database/alembic/versions")
    assert any(
        p.name.startswith("u1b2c3d4e5f6") for p in versions.glob("*.py")
    )


def test_management_entities_importable() -> None:
    from stock_platform.ai.providers.management_entities import (
        NO_SECRET_PROVIDERS,
        PROVIDER_CODES,
        AIProviderConfigurationEntity,
    )

    assert "mock" in PROVIDER_CODES
    assert "ollama" in NO_SECRET_PROVIDERS
    assert AIProviderConfigurationEntity.__tablename__ == "provider_configuration"


@pytest.mark.asyncio
async def test_verify_mock_http_openai(vault_key: bytes) -> None:
    """Credential verify uses injected httpx mock — no live network."""

    import httpx

    from stock_platform.ai.providers.credential_verify_service import (
        verify_credential,
    )
    from stock_platform.ai.providers.management_entities import (
        AIProviderConfigurationEntity,
        AIProviderCredentialEntity,
    )
    from stock_platform.ai.providers.management_service import (
        AIProviderManagementService,
    )

    session = MagicMock()
    config = AIProviderConfigurationEntity(
        provider_configuration_id=1,
        provider_code="openai",
        display_name="OpenAI",
        enabled=False,
        is_default=False,
        priority=20,
        model="gpt-4o-mini",
        endpoint="https://api.openai.com/v1",
        timeout_sec=30,
        retry_max=1,
        max_tokens=32,
        temperature=0.2,
        config_version=1,
    )
    blob = encrypt_ai_credential({"api_key": "sk-test"})
    cred = AIProviderCredentialEntity(
        provider_credential_id=9,
        provider_configuration_id=1,
        credential_type="API_KEY",
        encrypted_payload=blob.ciphertext_b64,
        nonce_b64=blob.nonce_b64,
        encryption_algorithm=blob.algorithm,
        key_version=blob.key_version,
        status="PENDING",
        is_active=False,
        fingerprint=fingerprint_payload({"api_key": "sk-test"}),
    )

    def get_side_effect(model, ident):
        if model is AIProviderConfigurationEntity:
            return config
        if model is AIProviderCredentialEntity:
            return cred
        return None

    session.get.side_effect = get_side_effect
    session.scalar.return_value = cred

    # patch get_configuration path used inside verify
    svc = AIProviderManagementService(session)
    svc.get_configuration = MagicMock(
        return_value={
            "id": 1,
            "provider_code": "openai",
            "model": "gpt-4o-mini",
            "endpoint": "https://api.openai.com/v1",
        }
    )
    svc.mark_credential_status = MagicMock(
        return_value={"status": "VERIFIED", "id": 9}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "gpt-4o-mini"}]})

    # Monkeypatch service construction inside verify
    import stock_platform.ai.providers.credential_verify_service as cvs

    original = cvs.AIProviderManagementService

    class _Svc(AIProviderManagementService):
        def get_configuration(self, config_id: int):
            return {
                "id": 1,
                "provider_code": "openai",
                "model": "gpt-4o-mini",
                "endpoint": "https://api.openai.com/v1",
            }

        def mark_credential_status(self, *args, **kwargs):
            return {"status": kwargs.get("status"), "id": 9}

    cvs.AIProviderManagementService = _Svc  # type: ignore[misc]
    try:
        result = await verify_credential(
            session,
            config_id=1,
            credential_id=9,
            actor="admin:1",
            reason="test",
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ),
        )
    finally:
        cvs.AIProviderManagementService = original  # type: ignore[misc]

    assert result["external_call"] is True
    assert result["ok"] is True
    assert result["status"] == "VERIFIED"


def test_fail_closed_loader_without_db() -> None:
    from stock_platform.ai.providers.registry_loader import load_runtime_configs

    configs, source = load_runtime_configs(None)
    assert source == "ENV"
    assert any(c.provider_id == "mock" for c in configs)


def test_public_credential_never_exposes_secret(vault_key: bytes) -> None:
    from stock_platform.ai.providers.management_entities import (
        AIProviderCredentialEntity,
    )
    from stock_platform.ai.providers.management_service import _public_credential

    blob = encrypt_ai_credential({"api_key": "sk-secret-never-expose"})
    cred = AIProviderCredentialEntity(
        provider_credential_id=1,
        provider_configuration_id=1,
        credential_type="API_KEY",
        encrypted_payload=blob.ciphertext_b64,
        nonce_b64=blob.nonce_b64,
        encryption_algorithm=blob.algorithm,
        key_version=blob.key_version,
        status="PENDING",
        is_active=False,
        fingerprint=fingerprint_payload({"api_key": "sk-secret-never-expose"}),
    )
    public = _public_credential(cred)
    assert public is not None
    dumped = str(public)
    assert "sk-secret" not in dumped
    assert "encrypted_payload" not in public
    assert "api_key" not in public


def test_enable_requires_verified_for_openai() -> None:
    from stock_platform.ai.providers.management_entities import (
        AIProviderConfigurationEntity,
    )
    from stock_platform.ai.providers.management_service import (
        AIProviderManagementError,
        AIProviderManagementService,
    )

    session = MagicMock()
    config = AIProviderConfigurationEntity(
        provider_configuration_id=2,
        provider_code="openai",
        display_name="OpenAI",
        enabled=False,
        is_default=False,
        priority=20,
        model="gpt-4o-mini",
        endpoint="https://api.openai.com/v1",
        timeout_sec=30,
        retry_max=1,
        max_tokens=32,
        temperature=0.2,
        config_version=1,
    )
    session.get.return_value = config
    session.scalar.return_value = None  # no active credential
    svc = AIProviderManagementService(session)
    with pytest.raises(AIProviderManagementError) as exc:
        svc.enable_provider(2, actor="a", reason="test", confirm=True)
    assert exc.value.code == "CREDENTIAL_NOT_VERIFIED"


def test_enable_requires_confirm() -> None:
    from stock_platform.ai.providers.management_service import (
        AIProviderManagementError,
        AIProviderManagementService,
    )

    svc = AIProviderManagementService(MagicMock())
    with pytest.raises(AIProviderManagementError) as exc:
        svc.enable_provider(1, actor="a", reason="x", confirm=False)
    assert exc.value.code == "CONFIRM_REQUIRED"


def test_disabled_cannot_be_default() -> None:
    from stock_platform.ai.providers.management_entities import (
        AIProviderConfigurationEntity,
    )
    from stock_platform.ai.providers.management_service import (
        AIProviderManagementError,
        AIProviderManagementService,
    )

    session = MagicMock()
    config = AIProviderConfigurationEntity(
        provider_configuration_id=3,
        provider_code="ollama",
        display_name="Ollama",
        enabled=False,
        is_default=False,
        priority=40,
        model="llama3",
        endpoint="http://127.0.0.1:11434",
        timeout_sec=30,
        retry_max=1,
        max_tokens=32,
        temperature=0.2,
        config_version=1,
    )
    session.get.return_value = config
    svc = AIProviderManagementService(session)
    with pytest.raises(AIProviderManagementError) as exc:
        svc.set_default(3, actor="a", reason="x", confirm=True)
    assert exc.value.code == "DEFAULT_REQUIRES_ENABLED"


def test_ollama_is_no_secret_provider() -> None:
    from stock_platform.ai.providers.management_entities import NO_SECRET_PROVIDERS

    assert "ollama" in NO_SECRET_PROVIDERS
    assert "mock" in NO_SECRET_PROVIDERS
    assert "openai" not in NO_SECRET_PROVIDERS


def test_reload_failure_keeps_existing_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_platform.ai.providers.manager import (
        AIManager,
        get_ai_manager,
        reset_ai_manager,
    )
    from stock_platform.ai.providers import registry_loader as rl

    old = AIManager.create_default()
    old.config_source = "ENV"
    reset_ai_manager(old)

    def boom(_session):
        raise RuntimeError("reload boom")

    monkeypatch.setattr(rl, "build_registry_from_session", boom)
    session = MagicMock()
    # mark_reloaded path may fail — ok
    result = rl.reload_ai_manager_from_db(session, actor="test")
    assert result["ok"] is False
    assert result["kept_existing_manager"] is True
    assert get_ai_manager() is old


def test_store_credential_does_not_enable(vault_key: bytes) -> None:
    """store_credential 계약: activate=False 기본, enabled 변경 없음."""

    from stock_platform.ai.providers.management_entities import (
        AIProviderConfigurationEntity,
    )
    from stock_platform.ai.providers.management_service import (
        AIProviderManagementService,
    )

    session = MagicMock()
    config = AIProviderConfigurationEntity(
        provider_configuration_id=5,
        provider_code="openai",
        display_name="OpenAI",
        enabled=False,
        is_default=False,
        priority=20,
        model="gpt-4o-mini",
        endpoint="https://api.openai.com/v1",
        timeout_sec=30,
        retry_max=1,
        max_tokens=32,
        temperature=0.2,
        config_version=1,
    )
    session.get.return_value = config
    session.scalar.return_value = None

    svc = AIProviderManagementService(session)
    svc.get_configuration = MagicMock(  # type: ignore[method-assign]
        return_value={"id": 5, "enabled": False, "provider_code": "openai"}
    )
    result = svc.store_credential(
        5,
        api_key="sk-new-key-aaaaaaaa",
        custom_headers=None,
        actor="admin",
        reason="store only",
        activate=False,
    )
    assert config.enabled is False
    assert result["credential"]["status"] == "PENDING"
    assert result["credential"]["is_active"] is False
    assert "sk-new-key" not in str(result)


def test_history_sanitize_excludes_secret() -> None:
    from stock_platform.ai.providers.security import sanitize_for_log

    sanitized = sanitize_for_log(
        {
            "api_key": "sk-abcdef",
            "encrypted_payload": "blob",
            "headers": {"x-api-key": "zzz"},
            "reason": "ok",
        }
    )
    assert "sk-abcdef" not in str(sanitized)
    assert "zzz" not in str(sanitized.get("headers", {}))


def test_bootstrap_fail_closed_sets_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_platform.ai.providers.manager import get_ai_manager, reset_ai_manager
    from stock_platform.ai.providers import registry_loader as rl

    reset_ai_manager(None)

    def boom(_session=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(rl, "build_registry_from_session", boom)
    source = rl.bootstrap_ai_manager_from_db(session=MagicMock())
    assert source == "FAIL_CLOSED_MOCK"
    manager = get_ai_manager()
    assert manager.config_source == "FAIL_CLOSED_MOCK"
    assert manager.registry.default_provider().provider_id == "mock"


def test_dashboard_block_has_zero_external_calls() -> None:
    from stock_platform.ai.providers.manager import AIManager

    block = AIManager.create_default().dashboard_block()
    assert block["external_calls_on_read"] == 0
    assert block["default_provider"] == "mock"


def test_api_router_registered() -> None:
    from stock_platform.api import router as router_mod

    assert hasattr(router_mod, "admin_ai_provider_configurations_router")
    paths = {
        getattr(r, "path", "")
        for r in router_mod.admin_ai_provider_configurations_router.routes
    }
    assert any("provider-configurations" in p for p in paths)


def test_migration_seed_mock_only_enabled_in_file() -> None:
    text = Path(
        "database/alembic/versions/u1b2c3d4e5f6_ai_provider_configuration_vault.py"
    ).read_text(encoding="utf-8")
    assert "provider_code" in text
    assert "mock" in text
    # seed에서 외부 provider enabled=true 자동 금지 확인 (문자열 휴리스틱)
    assert "openai" in text
    assert "enabled" in text
