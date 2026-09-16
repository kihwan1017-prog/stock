"""STEP 11-4 — 코드 레벨 Core Safety (DB로 해제 불가)."""

from __future__ import annotations

import re
from typing import Any

# LIVE/ARM/주문/스케줄러 등 — DB Policy 비활성과 무관하게 항상 적용
CORE_BLOCK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("ORDER_EXECUTE", r"\b(submit[_\s-]?order|place[_\s-]?order|execute[_\s-]?trade|broker\s*submit)\b"),
    ("LIVE_ON", r"\b(live\s*(on|enable|true|1)|enable[_\s-]?live|live_trading\s*=?\s*true)\b"),
    ("ARM_ON", r"\b(arm\s*(on|enable|true|1)|enable[_\s-]?arm)\b"),
    ("SCHEDULER_START", r"\b(start[_\s-]?scheduler|scheduler[_\s-]?start|resume[_\s-]?scheduler)\b"),
    ("RUNTIME_RESUME", r"\b(runtime[_\s-]?resume|resume[_\s-]?runtime)\b"),
    ("KILL_SWITCH_OFF", r"\b(kill[_\s-]?switch\s*(off|disable)|disable[_\s-]?kill)\b"),
    ("CREDENTIAL_EXFIL", r"\b(api[_\s-]?key|access[_\s-]?token|refresh[_\s-]?token|broker[_\s-]?token|master[_\s-]?key)\b"),
    ("ADMIN_ESCALATION", r"\b(grant[_\s-]?admin|become[_\s-]?admin|role\s*=\s*admin)\b"),
    ("STRATEGY_ACTIVATE", r"\b(activate[_\s-]?strategy|deploy[_\s-]?strategy|enable[_\s-]?strategy)\b"),
    ("SHELL_EXEC", r"\b(rm\s+-rf|powershell|cmd\.exe|/bin/sh|subprocess\.|os\.system)\b"),
    ("SQL_MUTATION", r"\b(drop\s+table|truncate\s+table|delete\s+from|alter\s+table)\b"),
    ("HTTP_SIDE_EFFECT", r"\b(curl\s+|wget\s+|requests\.(post|put|delete)|httpx\.(post|put))\b"),
)

CORE_INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("IGNORE_PREVIOUS", r"(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)"),
    ("REVEAL_SYSTEM", r"(reveal|show|print|leak)\s+(the\s+)?(system\s+prompt|hidden\s+instructions?)"),
    ("ROLE_HIJACK", r"(you\s+are\s+now|act\s+as|pretend\s+to\s+be)\s+(an?\s+)?(admin|root|unrestricted)"),
    ("POLICY_BYPASS", r"(bypass|disable|override)\s+(safety|policy|guardrail)"),
    ("TOOL_FORCE", r"(call|invoke|run)\s+(the\s+)?(tool|function|plugin)"),
)


def scan_core_safety(text: str) -> list[dict[str, str]]:
    """텍스트에서 Core Safety 위반 탐지."""

    hits: list[dict[str, str]] = []
    lowered = text.lower()
    for code, pattern in CORE_BLOCK_PATTERNS + CORE_INJECTION_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            hits.append({"code": code, "severity": "BLOCK"})
    return hits


def scan_forbidden_fields(payload: Any, path: str = "") -> list[str]:
    """출력 JSON에서 금지 필드 탐지."""

    from stock_platform.ai.prompt.task_types import FORBIDDEN_OUTPUT_FIELDS

    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_l = str(key).lower()
            full = f"{path}.{key_l}" if path else key_l
            if key_l in FORBIDDEN_OUTPUT_FIELDS:
                found.append(full)
            found.extend(scan_forbidden_fields(value, full))
    elif isinstance(payload, list):
        for idx, item in enumerate(payload[:200]):
            found.extend(scan_forbidden_fields(item, f"{path}[{idx}]"))
    return found
