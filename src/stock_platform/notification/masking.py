"""민 필드 마스킹 — 토큰/시크릿 알림 유출 방지."""

from __future__ import annotations

from typing import Any

_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "secret",
        "secret_key",
        "api_key",
        "apikey",
        "bot_token",
        "telegram_bot_token",
        "jwt",
        "authorization",
        "password",
        "arm_token",
        "unlock_token",
        "private_key",
        "client_secret",
        "credential",
        "credentials",
    }
)


def mask_sensitive(payload: Any, *, depth: int = 0) -> Any:
    """dict/list 재귀 마스킹. 원본을 바꾸지 않고 새 구조 반환."""

    if depth > 12:
        return "[TRUNCATED]"
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            key_l = str(key).lower()
            if key_l in _SENSITIVE_KEYS or any(
                s in key_l for s in ("secret", "token", "password", "credential")
            ):
                out[str(key)] = "***"
            else:
                out[str(key)] = mask_sensitive(value, depth=depth + 1)
        return out
    if isinstance(payload, list):
        return [mask_sensitive(item, depth=depth + 1) for item in payload[:200]]
    if isinstance(payload, str) and len(payload) > 800:
        return payload[:800] + "…"
    return payload
