"""STEP 11-6 — HTML/XML/광고/제어문자 정제 (의미 임의 수정 금지)."""

from __future__ import annotations

import hashlib
import re
from html import unescape

_SCRIPT_RE = re.compile(
    r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL
)
_STYLE_RE = re.compile(
    r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MULTI_NL_RE = re.compile(r"\n{3,}")

# 반복 문구 / 광고 / 면책 (제거해도 사실관계 변경 없음)
_BOILERPLATE_PATTERNS = [
    re.compile(r"저작권자[^\n]{0,80}", re.IGNORECASE),
    re.compile(r"무단\s*전재[^\n]{0,80}", re.IGNORECASE),
    re.compile(r"관련\s*기사\s*더\s*보기[^\n]{0,40}", re.IGNORECASE),
    re.compile(r"기자\s*[A-Za-z0-9._%+-]+@[^\s]+", re.IGNORECASE),
    re.compile(r"광고\s*문의[^\n]{0,60}", re.IGNORECASE),
    re.compile(r"본\s*기사는[^\n]{0,120}", re.IGNORECASE),
    re.compile(r"전자공시시스템[^\n]{0,80}", re.IGNORECASE),
    re.compile(r"페이지\s*\d+\s*/\s*\d+", re.IGNORECASE),
]


def strip_html(text: str) -> str:
    """script/style/태그 제거. 표는 줄바꿈으로 대략 보존."""

    if not text:
        return ""
    cleaned = _SCRIPT_RE.sub(" ", text)
    cleaned = _STYLE_RE.sub(" ", cleaned)
    # 표 셀 구분 보존
    cleaned = re.sub(r"</t[dh]>", " | ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</tr>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</p>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = _TAG_RE.sub(" ", cleaned)
    return unescape(cleaned)


def remove_boilerplate(text: str) -> str:
    out = text
    for pat in _BOILERPLATE_PATTERNS:
        out = pat.sub(" ", out)
    return out


def normalize_whitespace(text: str) -> str:
    out = _CONTROL_RE.sub("", text)
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    out = _MULTI_SPACE_RE.sub(" ", out)
    out = _MULTI_NL_RE.sub("\n\n", out)
    return out.strip()


def sanitize_document_text(raw: str, *, kind: str = "news") -> dict[str, str | bool]:
    """정제 파이프라인. 웹 크롤링 없음."""

    had_html = "<" in (raw or "") and ">" in (raw or "")
    body = strip_html(raw or "") if had_html else (raw or "")
    body = remove_boilerplate(body)
    body = normalize_whitespace(body)
    return {
        "normalized_body": body,
        "had_html": had_html,
        "kind": kind,
        "content_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
