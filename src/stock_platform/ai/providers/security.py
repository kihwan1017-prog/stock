"""STEP 11-1 — API Key / PII 마스킹."""

from __future__ import annotations

import re
from typing import Any

_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "secret",
        "token",
        "password",
        "authorization",
        "bearer",
        "openai_api_key",
        "anthropic_api_key",
        "gemini_api_key",
        "claude_api_key",
        "encrypted_payload",
        "x-api-key",
        "x_api_key",
        "custom_headers",
    }
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_KEY_LIKE_RE = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|AIza[A-Za-z0-9_\-]{10,}|sk-ant-[A-Za-z0-9\-_]{10,})"
)


def mask_secret(value: str | None, *, visible: int = 4) -> str:
    """시크릿 마스킹 — 로그/응답용."""

    if not value:
        return ""
    text = str(value)
    if len(text) <= visible:
        return "*" * len(text)
    return f"{'*' * max(4, len(text) - visible)}{text[-visible:]}"


def mask_pii(text: str | None) -> str:
    if not text:
        return ""
    masked = _EMAIL_RE.sub("[EMAIL]", text)
    masked = _KEY_LIKE_RE.sub("[SECRET]", masked)
    return masked


def sanitize_for_log(payload: dict[str, Any] | None) -> dict[str, Any]:
    """중첩 dict에서 시크릿 키 마스킹."""

    if not payload:
        return {}
    result: dict[str, Any] = {}
    for key, value in payload.items():
        key_l = str(key).lower()
        key_norm = key_l.replace("-", "_")
        is_secret = (
            key_l in _SECRET_KEYS
            or key_norm in _SECRET_KEYS
            or any(
                s in key_norm
                for s in (
                    "api_key",
                    "secret",
                    "token",
                    "password",
                    "authorization",
                    "bearer",
                    "encrypted_payload",
                )
            )
        )
        if is_secret:
            result[key] = mask_secret(str(value) if value is not None else "")
        elif isinstance(value, dict):
            result[key] = sanitize_for_log(value)
        elif isinstance(value, str):
            result[key] = mask_pii(value)
        else:
            result[key] = value
    return result
