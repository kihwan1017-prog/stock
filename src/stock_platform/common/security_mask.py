"""민감정보 마스킹 (로그·Audit detail). STEP62."""

from __future__ import annotations

from typing import Any

_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "client_secret",
    "bot_token",
    "refresh",
    "cookie",
    "set-cookie",
    "jwt",
    "private_key",
)


def mask_secret(value: str | None, *, visible: int = 4) -> str:
    if not value:
        return ""
    text = str(value)
    if len(text) <= visible:
        return "***"
    return text[:visible] + "***"


def mask_account_number(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if len(text) <= 4:
        return "****"
    return text[:2] + ("*" * max(len(text) - 4, 2)) + text[-2:]


def mask_email(value: str | None) -> str:
    if not value or "@" not in value:
        return "***"
    local, _, domain = value.partition("@")
    if not local:
        return "***@" + domain
    if len(local) == 1:
        return local + "***@" + domain
    return local[:2] + "***@" + domain


def mask_ip(value: str | None) -> str:
    """IPv4 중간 옥텟 마스킹. IPv6는 앞뒤만 남김."""

    if not value:
        return ""
    text = str(value).strip()
    if "." in text and ":" not in text:
        parts = text.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.***.***.{parts[3]}"
        return "***"
    if ":" in text:
        if len(text) <= 8:
            return "***"
        return text[:4] + "***" + text[-4:]
    return "***"


def mask_chat_id(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if len(text) <= 4:
        return "***"
    return text[:3] + "***" + text[-3:]


def redact_mapping(data: Any, *, depth: int = 0) -> Any:
    """dict/list 재귀 마스킹 (깊이 제한)."""

    if depth > 6:
        return "***"
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            lowered = str(key).lower()
            if any(frag in lowered for frag in _SENSITIVE_KEY_FRAGMENTS):
                out[key] = mask_secret(str(value) if value is not None else "")
            elif "account" in lowered and "number" in lowered:
                out[key] = mask_account_number(
                    str(value) if value is not None else ""
                )
            elif lowered in {"email", "user_email"}:
                out[key] = mask_email(str(value) if value is not None else "")
            else:
                out[key] = redact_mapping(value, depth=depth + 1)
        return out
    if isinstance(data, list):
        return [redact_mapping(item, depth=depth + 1) for item in data[:100]]
    return data


def structlog_redact_processor(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    _ = (logger, method_name)
    return redact_mapping(event_dict)  # type: ignore[return-value]
