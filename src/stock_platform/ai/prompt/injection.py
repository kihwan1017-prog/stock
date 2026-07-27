"""STEP 11-4 — Prompt Injection / Secret / PII 탐지."""

from __future__ import annotations

import re
from typing import Any

from stock_platform.ai.prompt.core_safety import scan_core_safety
from stock_platform.ai.providers.security import mask_pii

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|sk-ant-[A-Za-z0-9\-_]{10,}|"
    r"AIza[A-Za-z0-9_\-]{10,}|"
    r"Bearer\s+[A-Za-z0-9\-._~+/]+=*)",
    re.IGNORECASE,
)
_PII_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PII_PHONE = re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b")
_PII_RRN = re.compile(r"\b\d{6}-?[1-4]\d{6}\b")


def has_control_chars(text: str) -> bool:
    return bool(_CONTROL_CHAR_RE.search(text))


def detect_secrets(text: str) -> list[str]:
    return [m.group(0)[:8] + "…" for m in _SECRET_RE.finditer(text)]


def detect_pii(text: str) -> list[str]:
    hits: list[str] = []
    if _PII_EMAIL.search(text):
        hits.append("EMAIL")
    if _PII_PHONE.search(text):
        hits.append("PHONE")
    if _PII_RRN.search(text):
        hits.append("RRN")
    return hits


def inspect_text_security(text: str) -> dict[str, Any]:
    """렌더/응답 공통 보안 검사."""

    core = scan_core_safety(text)
    secrets = detect_secrets(text)
    pii = detect_pii(text)
    blocked = bool(core) or bool(secrets)
    return {
        "blocked": blocked,
        "core_hits": core,
        "secrets_detected": len(secrets) > 0,
        "pii_detected": pii,
        "control_chars": has_control_chars(text),
        "sanitized_preview": mask_pii(text[:500]),
    }
