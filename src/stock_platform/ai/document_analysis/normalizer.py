"""STEP 11-6 — 뉴스/공시 입력 정규화 (크롤링 없음)."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.orm import Session

from stock_platform.ai.document_analysis.injection_guard import (
    inspect_document_injection,
    wrap_untrusted,
)
from stock_platform.ai.document_analysis.sanitizer import sanitize_document_text
from stock_platform.disclosure.models import DartDisclosure
from stock_platform.news.models import NewsArticle, NewsArticleSymbol


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url.strip())
        # tracking 파라미터 제거
        qs = parse_qs(parsed.query, keep_blank_values=False)
        drop = {k for k in qs if k.lower().startswith("utm_") or k in {"fbclid", "gclid"}}
        for k in drop:
            qs.pop(k, None)
        query = urlencode({k: v[0] for k, v in qs.items()}, doseq=False)
        path = parsed.path.rstrip("/") or "/"
        return urlunparse(
            (parsed.scheme.lower(), parsed.netloc.lower(), path, "", query, "")
        )
    except Exception:  # noqa: BLE001
        return url.strip()


def normalize_title(title: str | None) -> str:
    return " ".join((title or "").split()).strip().lower()


class AIDocumentNormalizer:
    def __init__(self, session: Session) -> None:
        self._session = session

    def load_news(self, article_id: int) -> dict[str, Any]:
        row = self._session.get(NewsArticle, article_id)
        if row is None:
            raise LookupError("NEWS_NOT_FOUND")
        symbols = list(
            self._session.scalars(
                select(NewsArticleSymbol).where(
                    NewsArticleSymbol.article_id == article_id
                )
            )
        )
        # 본문 없음 — title+description+raw_data 요약만 (자동 크롤 금지)
        parts = [row.title or ""]
        if row.description:
            parts.append(row.description)
        raw = row.raw_data or {}
        if isinstance(raw, dict):
            for key in ("body", "content", "summary"):
                if raw.get(key):
                    parts.append(str(raw[key]))
        joined = "\n\n".join(p for p in parts if p)
        sanitized = sanitize_document_text(joined, kind="news")
        body = str(sanitized["normalized_body"])
        body_only_title = not bool(row.description) and "body" not in (raw or {})
        injection = inspect_document_injection(body)
        related = [
            {"market_code": s.market_code, "symbol": s.symbol}
            for s in symbols
        ]
        if row.symbol:
            related.append(
                {"market_code": row.exchange_code, "symbol": row.symbol}
            )
        # dedupe
        seen: set[str] = set()
        uniq = []
        for item in related:
            key = f"{item['market_code']}:{item['symbol']}"
            if key not in seen:
                seen.add(key)
                uniq.append(item)

        source_key = row.content_hash
        source_version = "1"
        canonical = normalize_url(row.original_link or row.naver_link)
        payload = {
            "document_type": "NEWS",
            "source_document_id": row.article_id,
            "source_document_key": source_key,
            "source_version": source_version,
            "source": row.source_code,
            "publisher": None,
            "title": row.title,
            "title_normalized": normalize_title(row.title),
            "published_at": (
                row.published_at.isoformat() if row.published_at else None
            ),
            "collected_at": (
                row.created_at.isoformat() if row.created_at else None
            ),
            "canonical_url": canonical,
            "summary": row.description,
            "normalized_body": body,
            "related_symbols": uniq,
            "market_type": row.exchange_code,
            "symbol": row.symbol,
            "language": "ko",
            "content_hash": str(sanitized["content_hash"]),
            "body_from_title_only": body_only_title,
            "wrapped_body": wrap_untrusted("NEWS", body),
            "injection": injection,
            "had_html": sanitized["had_html"],
        }
        payload["normalized_content_hash"] = hashlib.sha256(
            json.dumps(
                {
                    "key": source_key,
                    "title": payload["title_normalized"],
                    "url": canonical,
                    "body": body,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        return payload

    def load_disclosure(self, disclosure_id: int) -> dict[str, Any]:
        row = self._session.get(DartDisclosure, disclosure_id)
        if row is None:
            raise LookupError("DISCLOSURE_NOT_FOUND")
        parts = [
            f"보고서명: {row.report_name}",
            f"기업: {row.corp_name} ({row.corp_code})",
            f"종목코드: {row.stock_code or ''}",
            f"접수번호: {row.receipt_no}",
            f"접수일: {row.receipt_date}",
            f"제출인: {row.filer_name or ''}",
            f"비고: {row.remark or ''}",
            f"정정여부: {row.is_correction}",
            f"관련접수번호: {row.related_receipt_no or ''}",
        ]
        raw = row.raw_data or {}
        if isinstance(raw, dict):
            for key in ("body", "content", "summary", "report_nm"):
                if raw.get(key):
                    parts.append(str(raw[key]))
        joined = "\n".join(parts)
        sanitized = sanitize_document_text(joined, kind="disclosure")
        body = str(sanitized["normalized_body"])
        injection = inspect_document_injection(body)
        source_key = row.receipt_no
        source_version = "correction" if row.is_correction else "original"
        payload = {
            "document_type": "DISCLOSURE",
            "source_document_id": row.disclosure_id,
            "source_document_key": source_key,
            "source_version": source_version,
            "receipt_no": row.receipt_no,
            "corp_code": row.corp_code,
            "corp_name": row.corp_name,
            "stock_code": row.stock_code,
            "report_name": row.report_name,
            "report_code": row.category_code,
            "submitted_at": row.receipt_date.isoformat(),
            "filer_name": row.filer_name,
            "disclosure_type": row.category_code,
            "is_correction": bool(row.is_correction),
            "original_receipt_no": row.related_receipt_no,
            "normalized_body": body,
            "attachment_metadata": [],
            "content_hash": str(sanitized["content_hash"]),
            "wrapped_body": wrap_untrusted("DISCLOSURE", body),
            "injection": injection,
            "market_type": "KRX",
            "symbol": row.stock_code,
            "company_id": row.corp_code,
            "had_html": sanitized["had_html"],
        }
        payload["normalized_content_hash"] = hashlib.sha256(
            json.dumps(
                {
                    "receipt_no": source_key,
                    "version": source_version,
                    "body": body,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        return payload
