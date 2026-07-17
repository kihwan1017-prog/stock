from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Any

from stock_platform.ai.ollama_client import OllamaClient
from stock_platform.news.naver_client import NaverNewsClient
from stock_platform.news.repository import NewsRepository


TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")


NEWS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "sentiment_score": {
            "type": "number",
            "minimum": -100,
            "maximum": 100,
        },
        "importance_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 100,
        },
        "risks": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "summary",
        "sentiment_score",
        "importance_score",
        "risks",
    ],
    "additionalProperties": False,
}


@dataclass(slots=True)
class NewsSyncResult:
    exchange_code: str
    symbol: str
    fetched_count: int
    unique_count: int
    saved_count: int
    duplicate_skipped: int


class NewsService:
    def __init__(
        self,
        *,
        repository: NewsRepository,
        naver_client: NaverNewsClient,
        ollama_client: OllamaClient,
        model_name: str,
    ) -> None:
        self._repository = repository
        self._naver_client = naver_client
        self._ollama_client = ollama_client
        self._model_name = model_name

    async def sync(
        self,
        *,
        exchange_code: str,
        symbol: str,
        query: str,
        display: int = 100,
    ) -> int:
        result = await self.sync_detailed(
            exchange_code=exchange_code,
            symbol=symbol,
            query=query,
            display=display,
        )
        return result.saved_count

    async def sync_detailed(
        self,
        *,
        exchange_code: str,
        symbol: str,
        query: str,
        display: int = 100,
    ) -> NewsSyncResult:
        normalized_exchange = exchange_code.strip().upper()
        normalized_symbol = symbol.strip().upper()

        try:
            body = await self._naver_client.search(
                query=query,
                display=display,
                start=1,
                sort="date",
            )
        except Exception as exc:
            self._repository.record_failure(
                exchange_code=normalized_exchange,
                symbol=normalized_symbol,
                query_text=query,
                error_message=str(exc)[:2000],
                source_code="NAVER",
                extra_data={"display": display},
            )
            raise

        rows: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        duplicate_skipped = 0

        for item in body.get("items") or []:
            title = self._clean_html(str(item.get("title", "")))
            description = self._clean_html(
                str(item.get("description", ""))
            )
            original_link = (
                str(item.get("originallink") or "").strip() or None
            )
            naver_link = (
                str(item.get("link") or "").strip() or None
            )
            link_key = (original_link or naver_link or "").lower()
            title_key = self._normalize_title(title)

            content_hash = hashlib.sha256(
                (
                    title_key
                    + "|"
                    + link_key
                ).encode("utf-8")
            ).hexdigest()

            # URL·제목·해시 기반 배치 내 중복 제거
            if (
                content_hash in seen_hashes
                or (link_key and link_key in seen_urls)
                or (title_key and title_key in seen_titles)
            ):
                duplicate_skipped += 1
                continue

            seen_hashes.add(content_hash)
            if link_key:
                seen_urls.add(link_key)
            if title_key:
                seen_titles.add(title_key)

            rows.append(
                {
                    "exchange_code": normalized_exchange,
                    "symbol": normalized_symbol,
                    "query_text": query,
                    "title": title,
                    "description": description or None,
                    "original_link": original_link,
                    "naver_link": naver_link,
                    "published_at": self._parse_pub_date(
                        item.get("pubDate")
                    ),
                    "source_code": "NAVER",
                    "content_hash": content_hash,
                    "raw_data": item,
                }
            )

        saved_count = self._repository.upsert_articles(rows)

        return NewsSyncResult(
            exchange_code=normalized_exchange,
            symbol=normalized_symbol,
            fetched_count=len(body.get("items") or []),
            unique_count=len(rows),
            saved_count=saved_count,
            duplicate_skipped=duplicate_skipped,
        )

    async def summarize(
        self,
        *,
        exchange_code: str,
        symbol: str,
        limit: int = 20,
    ) -> int:
        articles = self._repository.list_unsummarized(
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
            model_name=self._model_name,
            limit=limit,
        )

        saved = 0

        for article in articles:
            response = await self._ollama_client.chat_structured(
                system_prompt=(
                    "당신은 금융 뉴스 요약 보조자입니다. "
                    "제공된 제목과 설명만 사용하세요. "
                    "투자 권유나 수익 보장을 하지 마세요. "
                    "불확실하면 위험요소로 기록하세요."
                ),
                user_prompt=(
                    f"종목: {article.symbol}\n"
                    f"제목: {article.title}\n"
                    f"설명: {article.description or ''}\n"
                    "지정된 JSON 형식으로 요약하세요."
                ),
                response_schema=NEWS_SCHEMA,
            )

            self._repository.save_summary(
                article_id=article.article_id,
                model_name=self._model_name,
                summary_text=str(response.get("summary", "")),
                sentiment_score=Decimal(
                    str(response.get("sentiment_score", 0))
                ),
                importance_score=Decimal(
                    str(response.get("importance_score", 0))
                ),
                risks=[
                    str(value)
                    for value in response.get("risks", [])
                ],
            )
            saved += 1

        return saved

    def build_context(
        self,
        *,
        exchange_code: str,
        symbol: str,
        limit: int = 20,
    ) -> dict:
        rows = self._repository.list_context(
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
            limit=limit,
        )

        return {
            "news": [
                {
                    "title": article.title,
                    "published_at": (
                        article.published_at.isoformat()
                        if article.published_at
                        else None
                    ),
                    "collected_at": article.created_at.isoformat(),
                    "summary": (
                        summary.summary_text
                        if summary is not None
                        else article.description
                    ),
                    "sentiment_score": (
                        str(summary.sentiment_score)
                        if summary is not None
                        else None
                    ),
                    "importance_score": (
                        str(summary.importance_score)
                        if summary is not None
                        else None
                    ),
                    "risks": (
                        summary.risks
                        if summary is not None
                        else []
                    ),
                    "original_link": article.original_link,
                    "symbol": article.symbol,
                }
                for article, summary in rows
            ]
        }

    @staticmethod
    def _clean_html(value: str) -> str:
        return html.unescape(TAG_PATTERN.sub("", value)).strip()

    @staticmethod
    def _normalize_title(value: str) -> str:
        return WHITESPACE_PATTERN.sub(" ", value).strip().lower()

    @staticmethod
    def _parse_pub_date(value) -> datetime | None:
        if value in (None, ""):
            return None
        try:
            return parsedate_to_datetime(str(value))
        except (TypeError, ValueError):
            return None
