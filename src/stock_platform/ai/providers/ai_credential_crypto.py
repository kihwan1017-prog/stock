"""STEP 11-3 — AI Credential 암호화 (Broker AES-GCM 재사용)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from stock_platform.ai.providers.security import mask_secret
from stock_platform.broker.credential_crypto import (
    KEY_VERSION_V1,
    EncryptedBlob,
    VaultCryptoError,
    decrypt_payload,
    encrypt_payload,
    load_master_key,
    vault_available,
)

__all__ = [
    "VaultCryptoError",
    "ai_vault_available",
    "decrypt_ai_credential",
    "encrypt_ai_credential",
    "fingerprint_payload",
    "mask_api_key",
]


def ai_vault_available() -> bool:
    """Master Key 파일 존재 여부 (Broker와 동일 키 정책)."""

    return vault_available()


def require_ai_vault_key() -> bytes:
    key = load_master_key(required=True)
    assert key is not None
    return key


def fingerprint_payload(payload: dict[str, Any]) -> str:
    """동일 Key 여부 확인용 SHA-256 fingerprint (Secret 미포함 응답용)."""

    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def mask_api_key(api_key: str | None) -> str:
    return mask_secret(api_key or "", visible=4)


def encrypt_ai_credential(payload: dict[str, Any]) -> EncryptedBlob:
    if not ai_vault_available():
        raise VaultCryptoError("AI vault master key missing (Fail Closed)")
    return encrypt_payload(payload, key_version=KEY_VERSION_V1)


def decrypt_ai_credential(
    *,
    ciphertext_b64: str,
    nonce_b64: str,
    key_version: int,
    algorithm: str = "AES-256-GCM",
) -> dict[str, Any]:
    if not ai_vault_available():
        raise VaultCryptoError("AI vault master key missing (Fail Closed)")
    return decrypt_payload(
        ciphertext_b64=ciphertext_b64,
        nonce_b64=nonce_b64,
        key_version=key_version,
        algorithm=algorithm,
    )
