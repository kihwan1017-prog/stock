"""STEP 11-13 — Deterministic source fingerprint (no AI)."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from stock_platform.ai.candidate_lifecycle.constants import FINGERPRINT_VERSION

# null은 명시적 마커로 직렬화
_NULL_MARKER = "__NULL__"


def _canonicalize(value: Any) -> Any:
    if value is None:
        return _NULL_MARKER
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _canonicalize(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    return str(value)


def compute_fingerprint(fields: dict[str, Any]) -> str:
    """
    정렬된 canonical JSON 필드로 SHA-256 fingerprint 생성.

    null 값은 ``__NULL__`` 마커로 표현.
    """
    payload = {
        "fingerprint_version": FINGERPRINT_VERSION,
        "fields": _canonicalize(fields),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fingerprints_match(expected: str | None, actual: str | None) -> bool:
    if not expected or not actual:
        return False
    return expected == actual
