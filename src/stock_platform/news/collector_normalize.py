"""STEP N2 — 수집 텍스트/URL/시간 정규화 (의미 재작성 금지)."""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

TAG_PATTERN = re.compile(r"<[^>]+>", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")
# markdown-ish 인용/링크는 텍스트만 남김
MD_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def normalize_whitespace(value: str | None) -> str:
    return WHITESPACE_PATTERN.sub(" ", (value or "").strip())


def strip_html(value: str | None) -> str:
    """HTML 태그 제거 + unescape. 본문 의미는 유지."""

    if not value:
        return ""
    text = TAG_PATTERN.sub(" ", str(value))
    text = html.unescape(text)
    text = MD_LINK_PATTERN.sub(r"\1", text)
    return normalize_whitespace(text)


def normalize_title(value: str | None) -> str:
    return normalize_whitespace(strip_html(value))


def canonicalize_url(url: str | None) -> str | None:
    """tracking 파라미터 제거 + scheme/host/path 정규화."""

    if not url:
        return None
    raw = str(url).strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
        qs = parse_qs(parsed.query, keep_blank_values=False)
        drop = {
            k
            for k in qs
            if k.lower().startswith("utm_") or k.lower() in {"fbclid", "gclid"}
        }
        for key in drop:
            qs.pop(key, None)
        query = urlencode({k: v[0] for k, v in qs.items()}, doseq=False)
        path = parsed.path.rstrip("/") or "/"
        scheme = (parsed.scheme or "https").lower()
        netloc = parsed.netloc.lower()
        if not netloc:
            return raw
        return urlunparse((scheme, netloc, path, "", query, ""))
    except Exception:  # noqa: BLE001
        return raw


def parse_datetime_to_utc(value: Any) -> datetime | None:
    """ISO8601 / RFC2822 → timezone-aware UTC."""

    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    text = str(value).strip()
    if not text:
        return None

    # ISO8601 (Upbit listed_at)
    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


def identity_content_hash(*, source_code: str, external_id: str) -> str:
    """source+external_id 기반 안정 해시 — 본문 수정 시에도 동일 row."""

    key = f"{source_code.strip().upper()}|{str(external_id).strip()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def body_fingerprint(normalized_text: str) -> str:
    """내용 변경 감지용 (row identity와 분리)."""

    return hashlib.sha256(
        normalize_whitespace(normalized_text).encode("utf-8")
    ).hexdigest()
