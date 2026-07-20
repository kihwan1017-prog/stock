"""계좌번호 마스킹·해시 (원문 미저장·미응답)."""

from __future__ import annotations

import hashlib
import re


_ALNUM = re.compile(r"[^0-9A-Za-z]")


def normalize_account_number(raw: str) -> str:
    """비교·해시용으로 공백/기호를 제거한다."""

    return _ALNUM.sub("", (raw or "").strip())


def hash_account_ref(raw: str) -> str:
    """계좌번호 참조용 SHA-256 hex. 원문은 저장하지 않는다."""

    normalized = normalize_account_number(raw)
    if not normalized:
        raise ValueError("account_number is required")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def mask_account_number(raw: str | None) -> str | None:
    """응답용 마스킹 — 끝 4자리만 노출."""

    if raw is None:
        return None
    normalized = normalize_account_number(raw)
    if not normalized:
        return None
    if len(normalized) <= 4:
        return "****"
    return f"{'*' * (len(normalized) - 4)}{normalized[-4:]}"
