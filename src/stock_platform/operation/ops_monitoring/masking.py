"""STEP 8-11 — 민감정보 마스킹 (Dashboard 응답 전용)."""

from __future__ import annotations

import re
from typing import Any


_SECRET_KEY_RE = re.compile(
    r"(token|secret|password|api[_-]?key|access[_-]?key|authorization|"
    r"credential|arm_token|bearer|private)",
    re.IGNORECASE,
)


def mask_login_id(login_id: str | None) -> str | None:
    """로그인 ID 마스킹 — 앞 2·뒤 1만 노출."""

    if not login_id:
        return None
    text = str(login_id).strip()
    if len(text) <= 3:
        return "***"
    return f"{text[:2]}***{text[-1:]}"


def mask_broker_uuid(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}…{text[-4:]}"


def redact_mapping(payload: Any, *, depth: int = 0) -> Any:
    """dict/list 재귀 마스킹 — secret 키·긴 토큰 제거."""

    if depth > 6:
        return "[TRUNCATED]"
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            key_s = str(key)
            if _SECRET_KEY_RE.search(key_s):
                out[key_s] = "***"
                continue
            out[key_s] = redact_mapping(value, depth=depth + 1)
        return out
    if isinstance(payload, list):
        return [redact_mapping(item, depth=depth + 1) for item in payload[:50]]
    if isinstance(payload, str) and len(payload) > 120:
        return payload[:80] + "…"
    return payload


def mask_notification_body(text: str | None, *, max_len: int = 120) -> str | None:
    if text is None:
        return None
    cleaned = str(text)
    cleaned = re.sub(
        r"(?i)(arm[_-]?token|access[_-]?key|secret[_-]?key)\s*[:=]\s*\S+",
        r"\1=***",
        cleaned,
    )
    if len(cleaned) > max_len:
        return cleaned[:max_len] + "…"
    return cleaned
