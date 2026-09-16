"""STEP 8-5-2 — AES-256-GCM vault crypto unit tests."""

from __future__ import annotations

import base64
import os

import pytest

from stock_platform.broker.credential_crypto import (
    VaultCryptoError,
    decrypt_payload,
    encrypt_payload,
)


def _key() -> bytes:
    return os.urandom(32)


def test_encrypt_differs_from_plaintext() -> None:
    key = _key()
    plain = {"app_key": "ABC", "secret_key": "SECRET"}
    blob = encrypt_payload(plain, key=key)
    assert blob.ciphertext_b64 != "ABC"
    assert "SECRET" not in blob.ciphertext_b64
    assert blob.algorithm == "AES-256-GCM"
    assert blob.key_version == 1


def test_decrypt_roundtrip() -> None:
    key = _key()
    plain = {"access_key": "upbit-a", "secret_key": "upbit-s"}
    blob = encrypt_payload(plain, key=key)
    out = decrypt_payload(
        ciphertext_b64=blob.ciphertext_b64,
        nonce_b64=blob.nonce_b64,
        key_version=blob.key_version,
        key=key,
    )
    assert out == plain


def test_tampered_ciphertext_fails() -> None:
    key = _key()
    blob = encrypt_payload({"x": "1"}, key=key)
    raw = bytearray(base64.b64decode(blob.ciphertext_b64))
    raw[-1] ^= 0x01
    with pytest.raises(VaultCryptoError):
        decrypt_payload(
            ciphertext_b64=base64.b64encode(raw).decode("ascii"),
            nonce_b64=blob.nonce_b64,
            key_version=blob.key_version,
            key=key,
        )


def test_wrong_master_key_fails() -> None:
    key = _key()
    blob = encrypt_payload({"x": "1"}, key=key)
    with pytest.raises(VaultCryptoError):
        decrypt_payload(
            ciphertext_b64=blob.ciphertext_b64,
            nonce_b64=blob.nonce_b64,
            key_version=blob.key_version,
            key=_key(),
        )


def test_wrong_nonce_fails() -> None:
    key = _key()
    blob = encrypt_payload({"x": "1"}, key=key)
    bad_nonce = base64.b64encode(os.urandom(12)).decode("ascii")
    with pytest.raises(VaultCryptoError):
        decrypt_payload(
            ciphertext_b64=blob.ciphertext_b64,
            nonce_b64=bad_nonce,
            key_version=blob.key_version,
            key=key,
        )


def test_key_version_in_aad() -> None:
    key = _key()
    blob = encrypt_payload({"x": "1"}, key=key, key_version=1)
    with pytest.raises(VaultCryptoError):
        decrypt_payload(
            ciphertext_b64=blob.ciphertext_b64,
            nonce_b64=blob.nonce_b64,
            key_version=2,
            key=key,
        )
