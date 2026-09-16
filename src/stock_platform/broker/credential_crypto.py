"""STEP 8-5-2 — Broker Credential Vault AES-256-GCM.

Master Key는 파일에서만 로드한다 (소스/DB 금지).
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from stock_platform.common.settings import get_settings


ALGORITHM = "AES-256-GCM"
KEY_VERSION_V1 = 1
NONCE_SIZE = 12


class VaultCryptoError(RuntimeError):
    """암호화·복호화·키 로딩 실패."""


@dataclass(frozen=True, slots=True)
class EncryptedBlob:
    ciphertext_b64: str
    nonce_b64: str
    algorithm: str
    key_version: int


def resolve_master_key_path() -> Path | None:
    """BROKER_VAULT_MASTER_KEY_FILE 또는 기본 secrets 경로."""

    settings = get_settings()
    configured = getattr(
        settings, "broker_vault_master_key_file", None
    )
    if configured and str(configured).strip():
        return Path(str(configured).strip())
    # 기본: 레거시 secrets 디렉터리 (있으면)
    default = Path(r"E:\StockTrading\secrets\broker-vault-master.key")
    if default.is_file():
        return default
    env_override = os.environ.get("BROKER_VAULT_MASTER_KEY_FILE", "").strip()
    if env_override:
        return Path(env_override)
    return None


def load_master_key(*, required: bool = False) -> bytes | None:
    path = resolve_master_key_path()
    if path is None or not path.is_file():
        if required:
            raise VaultCryptoError(
                "Broker vault master key file not found"
            )
        return None
    raw = path.read_bytes()
    # base64 또는 raw 32 bytes
    key: bytes
    try:
        text = raw.strip()
        if len(text) == 32:
            key = text
        else:
            key = base64.b64decode(text, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise VaultCryptoError("Invalid master key file format") from exc
    if len(key) != 32:
        raise VaultCryptoError(
            "Master key must be 32 bytes (AES-256)"
        )
    return key


def encrypt_payload(
    plaintext: dict[str, Any],
    *,
    key: bytes | None = None,
    key_version: int = KEY_VERSION_V1,
) -> EncryptedBlob:
    master = key if key is not None else load_master_key(required=True)
    assert master is not None
    nonce = os.urandom(NONCE_SIZE)
    aes = AESGCM(master)
    data = json.dumps(plaintext, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    # associated data에 key_version 포함 — 변조 탐지
    aad = f"v{key_version}".encode("ascii")
    ciphertext = aes.encrypt(nonce, data, aad)
    return EncryptedBlob(
        ciphertext_b64=base64.b64encode(ciphertext).decode("ascii"),
        nonce_b64=base64.b64encode(nonce).decode("ascii"),
        algorithm=ALGORITHM,
        key_version=key_version,
    )


def decrypt_payload(
    *,
    ciphertext_b64: str,
    nonce_b64: str,
    key_version: int,
    algorithm: str = ALGORITHM,
    key: bytes | None = None,
) -> dict[str, Any]:
    if algorithm != ALGORITHM:
        raise VaultCryptoError(f"Unsupported algorithm: {algorithm}")
    master = key if key is not None else load_master_key(required=True)
    assert master is not None
    try:
        nonce = base64.b64decode(nonce_b64, validate=True)
        ciphertext = base64.b64decode(ciphertext_b64, validate=True)
        aes = AESGCM(master)
        aad = f"v{key_version}".encode("ascii")
        raw = aes.decrypt(nonce, ciphertext, aad)
        payload = json.loads(raw.decode("utf-8"))
    except VaultCryptoError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VaultCryptoError("Credential decryption failed") from exc
    if not isinstance(payload, dict):
        raise VaultCryptoError("Invalid decrypted payload type")
    return payload


def vault_available() -> bool:
    try:
        return load_master_key(required=False) is not None
    except VaultCryptoError:
        return False
