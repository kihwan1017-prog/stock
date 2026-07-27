"""STEP 11-6 — Prompt Injection / 문서 delimiter 가드."""

from __future__ import annotations

import base64
import re
from typing import Any

from stock_platform.ai.document_analysis.constants import (
    DISCLOSURE_DELIMITER_CLOSE,
    DISCLOSURE_DELIMITER_OPEN,
    NEWS_DELIMITER_CLOSE,
    NEWS_DELIMITER_OPEN,
)
from stock_platform.ai.prompt.injection import inspect_text_security

_INJECTION_HINTS = [
    re.compile(r"ignore\s+(all\s+)?previous", re.I),
    re.compile(r"disregard\s+(the\s+)?(system|above)", re.I),
    re.compile(r"reveal\s+(the\s+)?system\s+prompt", re.I),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"submit[_\s-]?order", re.I),
    re.compile(r"\bbuy\s+now\b", re.I),
    re.compile(r"\bsell\s+all\b", re.I),
    re.compile(r"enable\s+live", re.I),
    re.compile(r"api[_\s-]?key", re.I),
]
_B64_BLOCK = re.compile(r"(?:[A-Za-z0-9+/]{40,}={0,2})")
_HIDDEN_MD = re.compile(r"\[([^\]]*)\]\(\s*data:[^)]+\)", re.I)


def wrap_untrusted(document_type: str, body: str) -> str:
    if document_type == "DISCLOSURE":
        return (
            f"{DISCLOSURE_DELIMITER_OPEN}\n{body}\n{DISCLOSURE_DELIMITER_CLOSE}"
        )
    return f"{NEWS_DELIMITER_OPEN}\n{body}\n{NEWS_DELIMITER_CLOSE}"


def inspect_document_injection(text: str) -> dict[str, Any]:
    """외부 문서 전용 검사. 문서 내 지시는 실행하지 않음."""

    base = inspect_text_security(text)
    warnings: list[str] = []
    blocked = bool(base.get("blocked"))
    for pat in _INJECTION_HINTS:
        if pat.search(text or ""):
            warnings.append(f"injection_hint:{pat.pattern[:40]}")
    # Base64 긴 블록 디코드 시도 (실패해도 warning)
    for m in _B64_BLOCK.finditer(text or ""):
        chunk = m.group(0)
        try:
            decoded = base64.b64decode(chunk + "==", validate=False).decode(
                "utf-8", errors="ignore"
            )
            if any(p.search(decoded) for p in _INJECTION_HINTS):
                warnings.append("encoded_instruction_detected")
                blocked = True
        except Exception:  # noqa: BLE001
            continue
    if _HIDDEN_MD.search(text or ""):
        warnings.append("hidden_markdown_link")
    if base.get("control_chars"):
        warnings.append("unicode_control_chars")
    return {
        "blocked": blocked,
        "warnings": warnings,
        "security": base,
    }
