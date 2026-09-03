"""STEP N2 — Crypto News Collector (기존 Naver provider 재사용, 기본 OFF)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.common.settings import Settings, get_settings
from stock_platform.news.collector_constants import (
    CATEGORY_GENERAL,
    CRYPTO_NEWS_PROVIDER_NAVER,
    CRYPTO_NEWS_PROVIDER_NOT_AVAILABLE,
    LANGUAGE_KO,
    PLACEHOLDER_EXCHANGE_UPBIT,
    PLACEHOLDER_SYMBOL_CRYPTO,
    SOURCE_CODE_CRYPTO_NEWS,
    SOURCE_TYPE_CRYPTO_NEWS,
    STATUS_ACTIVE,
)
from stock_platform.news.collector_normalize import (
    body_fingerprint,
    canonicalize_url,
    identity_content_hash,
    normalize_title,
    parse_datetime_to_utc,
    strip_html,
)
from stock_platform.news.naver_client import NaverNewsClient, NaverNewsError
from stock_platform.news.repository import NewsRepository
from stock_platform.news.upbit_notice_collector import CollectorRunResult


@dataclass
class CryptoNewsProviderStatus:
    provider: str
    available: bool
    reason: str | None = None


def resolve_crypto_news_provider(
    settings: Settings | None = None,
) -> CryptoNewsProviderStatus:
    """유료 API 신규 가입 없이 기존 Naver만 후보."""

    settings = settings or get_settings()
    has_id = bool(str(getattr(settings, "naver_client_id", "") or "").strip())
    has_secret = bool(
        str(getattr(settings, "naver_client_secret", "") or "").strip()
    )
    if has_id and has_secret:
        return CryptoNewsProviderStatus(
            provider=CRYPTO_NEWS_PROVIDER_NAVER,
            available=True,
        )
    return CryptoNewsProviderStatus(
        provider=CRYPTO_NEWS_PROVIDER_NOT_AVAILABLE,
        available=False,
        reason="NAVER_CREDENTIALS_MISSING",
    )


class CryptoNewsCollector:
    """CRYPTO_NEWS — Symbol Mapping / AI 없음. Naver 미설정 시 no-op 보고."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
        naver_client: NaverNewsClient | None = None,
        repository: NewsRepository | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._naver = naver_client
        self._owns_client = naver_client is None
        self._repository = repository or NewsRepository(session)

    async def collect(self) -> CollectorRunResult:
        result = CollectorRunResult(
            source=SOURCE_CODE_CRYPTO_NEWS,
            source_type=SOURCE_TYPE_CRYPTO_NEWS,
        )
        # last_check와 별개로 "새 기사 존재 여부"를 판정하기 위한 스냅샷
        before_latest = self._repository.latest_published_at(
            source_code=SOURCE_CODE_CRYPTO_NEWS
        )
        before_dt: datetime | None = None
        if isinstance(before_latest, datetime):
            if before_latest.tzinfo is None:
                before_latest = before_latest.replace(tzinfo=timezone.utc)
            before_dt = before_latest
            result.cursor_published_at = before_latest.isoformat()
            result.published_at_before = before_latest.isoformat()

        status = resolve_crypto_news_provider(self._settings)
        if not status.available:
            result.last_error = CRYPTO_NEWS_PROVIDER_NOT_AVAILABLE
            result.samples = [
                {
                    "provider": status.provider,
                    "reason": status.reason,
                }
            ]
            return result

        client = self._naver or NaverNewsClient(settings=self._settings)
        try:
            display = max(
                1,
                min(
                    int(
                        getattr(
                            self._settings,
                            "crypto_news_collection_display",
                            20,
                        )
                    ),
                    50,
                ),
            )
            queries = self._resolve_queries()
            result.samples.append(
                {
                    "dynamic_queries": queries,
                    "dynamic_target_n": max(0, len(queries) - 1),
                }
            )
            for query in queries:
                body = await client.search(
                    query=query,
                    display=display,
                    start=1,
                    sort="date",
                )
                items = body.get("items") or []
                result.fetched_count += len(items)

                for item in items:
                    if not isinstance(item, dict):
                        result.parse_failure_count += 1
                        continue
                    try:
                        stored = self._normalize_and_store(item, query=query)
                    except Exception as exc:  # noqa: BLE001
                        result.parse_failure_count += 1
                        logger.info(
                            "crypto_news_item_parse_failed",
                            error=str(exc)[:200],
                        )
                        continue
                    if stored is None:
                        result.parse_failure_count += 1
                        continue
                    result.normalized_count += 1
                    action = stored["action"]
                    if action == "inserted":
                        result.inserted_count += 1
                    elif action == "updated":
                        result.updated_count += 1
                    else:
                        result.duplicate_count += 1
                    if len(result.samples) < 8:
                        result.samples.append(stored)

            self._session.commit()
        except (NaverNewsError, ValueError) as exc:
            self._session.rollback()
            result.failure_count += 1
            result.last_error = str(exc)[:500]
            self._repository.record_failure(
                exchange_code=PLACEHOLDER_EXCHANGE_UPBIT,
                symbol=PLACEHOLDER_SYMBOL_CRYPTO,
                query_text=SOURCE_CODE_CRYPTO_NEWS,
                error_message=str(exc)[:2000],
                source_code=SOURCE_CODE_CRYPTO_NEWS,
                extra_data={"source_type": SOURCE_TYPE_CRYPTO_NEWS},
            )
        except Exception as exc:  # noqa: BLE001
            self._session.rollback()
            result.failure_count += 1
            result.last_error = f"{type(exc).__name__}: {exc}"[:500]
        finally:
            if self._owns_client:
                await client.aclose()

        # 새 기사 존재 여부 증명을 위한 after-snapshot
        after_latest = self._repository.latest_published_at(
            source_code=SOURCE_CODE_CRYPTO_NEWS
        )
        after_dt: datetime | None = None
        if isinstance(after_latest, datetime):
            if after_latest.tzinfo is None:
                after_latest = after_latest.replace(tzinfo=timezone.utc)
            after_dt = after_latest
            result.published_at_after = after_latest.isoformat()

        if before_dt is None and after_dt is not None:
            result.had_new_items = True
            result.last_new_article_at = result.published_at_after
        elif before_dt is not None and after_dt is not None:
            result.had_new_items = after_dt > before_dt
            result.last_new_article_at = (
                result.published_at_after
                if result.had_new_items
                else result.published_at_before
            )
        elif before_dt is not None and after_dt is None:
            result.last_new_article_at = result.published_at_before
        return result

    def _resolve_queries(self) -> list[str]:
        """기본 쿼리 + 활성/후보 심볼 기반 bounded dynamic target."""

        base = str(
            getattr(
                self._settings,
                "crypto_news_collection_query",
                "업비트 암호화폐",
            )
        ).strip() or "업비트 암호화폐"
        max_extra = max(
            0,
            min(
                int(
                    getattr(
                        self._settings,
                        "crypto_news_dynamic_target_max",
                        8,
                    )
                ),
                15,
            ),
        )
        queries = [base]
        try:
            from stock_platform.news.intelligence.upbit_targets import (
                list_upbit_dynamic_news_targets,
            )

            for target in list_upbit_dynamic_news_targets(
                self._session, limit=max_extra
            ):
                q = str(target.get("query") or "").strip()
                if q and q not in queries:
                    queries.append(q)
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "crypto_news_dynamic_target_failed",
                error=f"{type(exc).__name__}: {exc}"[:200],
            )
        return queries

    def _normalize_and_store(
        self,
        item: dict[str, Any],
        *,
        query: str,
    ) -> dict[str, Any] | None:
        title = normalize_title(str(item.get("title") or ""))
        if not title:
            return None
        description = strip_html(str(item.get("description") or ""))
        original = (
            str(item.get("originallink") or item.get("link") or "").strip()
            or None
        )
        canonical = canonicalize_url(original) if original else None
        # external_id: URL 우선, 없으면 title+pubDate
        external_id = canonical or f"{title}|{item.get('pubDate') or ''}"
        content_hash = identity_content_hash(
            source_code=SOURCE_CODE_CRYPTO_NEWS,
            external_id=external_id,
        )
        published_at = parse_datetime_to_utc(item.get("pubDate"))
        collected_at = datetime.now(timezone.utc)
        text = description or title
        fingerprint = body_fingerprint(text)

        raw_data = {
            "source_type": SOURCE_TYPE_CRYPTO_NEWS,
            "external_id": external_id[:500],
            "canonical_url": canonical,
            "category": CATEGORY_GENERAL,
            "language": LANGUAGE_KO,
            "status": STATUS_ACTIVE,
            "collected_at": collected_at.isoformat(),
            "updated_at": collected_at.isoformat(),
            "body_fingerprint": fingerprint,
            "provider": CRYPTO_NEWS_PROVIDER_NAVER,
            "query": query,
            # Naver 원문 메타만 — 민감정보 없음
            "naver_link": str(item.get("link") or "")[:500] or None,
        }

        row = {
            "exchange_code": PLACEHOLDER_EXCHANGE_UPBIT,
            "symbol": PLACEHOLDER_SYMBOL_CRYPTO,
            "query_text": query[:300],
            "title": title,
            "description": description[:4000] if description else None,
            "original_link": canonical,
            "naver_link": str(item.get("link") or "").strip() or None,
            "published_at": published_at,
            "source_code": SOURCE_CODE_CRYPTO_NEWS,
            "content_hash": content_hash,
            "raw_data": raw_data,
        }
        action = self._repository.upsert_collector_article(row)
        return {
            "action": action,
            "external_id": external_id[:120],
            "title": title,
            "category": CATEGORY_GENERAL,
            "url": canonical,
            "published_at": published_at.isoformat() if published_at else None,
        }
