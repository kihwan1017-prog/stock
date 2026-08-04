"""LIVE Smoke / Order Execution — failure_code 정규화.

failure_code: 짧은 안정 코드 (varchar(80) 안전)
failure_summary / detail: 긴 사용자 메시지·복합 사유
"""

from __future__ import annotations

import re
from typing import Any

FAILURE_CODE_MAX_LEN = 80
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")

# Risk Engine 메시지 조각 → 안정 코드
_RISK_MESSAGE_CODE_MAP: tuple[tuple[str, str], ...] = (
    (
        "projected investment ratio exceeds limit",
        "RISK_INVESTMENT_RATIO_EXCEEDED",
    ),
    (
        "daily loss limit reached",
        "RISK_DAILY_LOSS_LIMIT_REACHED",
    ),
    (
        "projected symbol position exceeds",
        "RISK_SYMBOL_POSITION_LIMIT_EXCEEDED",
    ),
)


def normalize_failure_code(
    value: Any,
    *,
    fallback: str = "UNKNOWN_FAILURE",
) -> str:
    """대문자 영숫자+underscore, 최대 80자. 문장형 입력은 fallback."""

    raw = str(value or "").strip()
    fb = str(fallback or "UNKNOWN_FAILURE").strip().upper()
    if not _CODE_RE.match(fb):
        fb = "UNKNOWN_FAILURE"
    fb = fb[:FAILURE_CODE_MAX_LEN]

    if not raw:
        return fb

    # 사용자 문장·복합 사유는 code로 쓰지 않음
    if " " in raw or ";" in raw or len(raw) > FAILURE_CODE_MAX_LEN:
        return fb

    candidate = re.sub(r"[^A-Z0-9_]", "", raw.upper().replace("-", "_"))
    if not candidate or not _CODE_RE.match(candidate):
        return fb
    return candidate[:FAILURE_CODE_MAX_LEN]


def split_risk_detail_messages(blocked_reason: str | None) -> list[str]:
    """'; 'a; b; c' 형태 blocked_reason을 상세 목록으로 분리."""

    raw = str(blocked_reason or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(";")]
    return [p for p in parts if p]


def classify_risk_blocked_reason(
    blocked_reason: str | None,
) -> tuple[str, list[str], str]:
    """Risk blocked_reason → (failure_code, details[], summary).

    복합 사유면 RISK_ENGINE_BLOCKED + details 유지.
    단일 매칭이면 세부 코드.
    """

    details = split_risk_detail_messages(blocked_reason)
    summary = "; ".join(details) if details else (
        str(blocked_reason).strip() if blocked_reason else "Risk policy blocked this order."
    )

    matched_codes: list[str] = []
    for detail in details or [summary]:
        lower = detail.lower()
        for needle, code in _RISK_MESSAGE_CODE_MAP:
            if needle in lower:
                matched_codes.append(code)
                break

    unique_codes = list(dict.fromkeys(matched_codes))
    if len(unique_codes) == 1:
        code = unique_codes[0]
    elif unique_codes:
        code = "RISK_ENGINE_BLOCKED"
    else:
        # 이미 짧은 코드로 온 경우
        maybe = normalize_failure_code(
            blocked_reason, fallback="RISK_ENGINE_BLOCKED"
        )
        if maybe != "RISK_ENGINE_BLOCKED" and " " not in str(blocked_reason or ""):
            code = maybe
        else:
            code = "RISK_ENGINE_BLOCKED"

    return (
        normalize_failure_code(code, fallback="RISK_ENGINE_BLOCKED"),
        details if details else ([summary] if summary else []),
        summary[:2000],
    )


def apply_failure_fields(
    *,
    failure_code: str | None,
    failure_summary: str | None = None,
    fallback: str = "UNKNOWN_FAILURE",
) -> tuple[str, str | None]:
    """엔티티 저장용 (code, summary) 튜플."""

    code = normalize_failure_code(failure_code, fallback=fallback)
    summary = None
    if failure_summary is not None:
        text = str(failure_summary).strip()
        summary = text[:2000] if text else None
    # code로 쓰려던 긴 문장이 summary에만 남도록
    raw = str(failure_code or "").strip()
    if raw and (" " in raw or ";" in raw or len(raw) > FAILURE_CODE_MAX_LEN):
        if not summary:
            summary = raw[:2000]
    return code, summary
