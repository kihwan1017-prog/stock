"""STEP N2 — UPBIT Notice Collector: COLLECT → NORMALIZE → DEDUP → STORE."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.common.settings import Settings, get_settings
from stock_platform.news.collector_category import normalize_notice_category
from stock_platform.news.collector_constants import (
    LANGUAGE_KO,
    NOTICE_PUBLIC_URL_TEMPLATE,
    PLACEHOLDER_EXCHANGE_UPBIT,
    PLACEHOLDER_SYMBOL_NOTICE,
    SOURCE_CODE_UPBIT_NOTICE,
    SOURCE_TYPE_UPBIT_NOTICE,
    STATUS_ACTIVE,
    STATUS_UPDATED,
)
from stock_platform.news.collector_normalize import (
    body_fingerprint,
    canonicalize_url,
    identity_content_hash,
    normalize_title,
    parse_datetime_to_utc,
    strip_html,
)
from stock_platform.news.repository import NewsRepository
from stock_platform.news.upbit_notice_client import (
    UpbitNoticeClient,
    UpbitNoticeClientError,
)


@dataclass
class CollectorRunResult:
    source: str = SOURCE_CODE_UPBIT_NOTICE
    source_type: str = SOURCE_TYPE_UPBIT_NOTICE
    fetched_count: int = 0
    normalized_count: int = 0
    inserted_count: int = 0
    duplicate_count: int = 0
    updated_count: int = 0
    parse_failure_count: int = 0
    failure_count: int = 0
    last_error: str | None = None
    cursor_published_at: str | None = None
    published_at_before: str | None = None
    published_at_after: str | None = None
    last_new_article_at: str | None = None
    had_new_items: bool = False
    samples: list[dict[str, Any]] = field(default_factory=list)


class UpbitNoticeCollector:
    """공식 공지만 수집. Symbol Mapping / AI / Scanner 연동 없음."""

    def __init__(
        self,
        session: Session,
        *,
        client: UpbitNoticeClient | None = None,
        settings: Settings | None = None,
        repository: NewsRepository | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None
        self._repository = repository or NewsRepository(session)

    async def collect(self, *, fetch_bodies: bool | None = None) -> CollectorRunResult:
        result = CollectorRunResult()
        client = self._client or UpbitNoticeClient(settings=self._settings)
        try:
            await self._collect_into(result, client, fetch_bodies=fetch_bodies)
            self._session.commit()
        except UpbitNoticeClientError as exc:
            self._session.rollback()
            result.failure_count += 1
            result.last_error = str(exc)[:500]
            self._repository.record_failure(
                exchange_code=PLACEHOLDER_EXCHANGE_UPBIT,
                symbol=PLACEHOLDER_SYMBOL_NOTICE,
                query_text=SOURCE_CODE_UPBIT_NOTICE,
                error_message=str(exc)[:2000],
                source_code=SOURCE_CODE_UPBIT_NOTICE,
                extra_data={"source_type": SOURCE_TYPE_UPBIT_NOTICE},
            )
            logger.warning(
                "upbit_notice_collect_failed",
                error=result.last_error,
            )
        except Exception as exc:  # noqa: BLE001 — failure isolation
            self._session.rollback()
            result.failure_count += 1
            result.last_error = f"{type(exc).__name__}: {exc}"[:500]
            try:
                self._repository.record_failure(
                    exchange_code=PLACEHOLDER_EXCHANGE_UPBIT,
                    symbol=PLACEHOLDER_SYMBOL_NOTICE,
                    query_text=SOURCE_CODE_UPBIT_NOTICE,
                    error_message=str(exc)[:2000],
                    source_code=SOURCE_CODE_UPBIT_NOTICE,
                    extra_data={"source_type": SOURCE_TYPE_UPBIT_NOTICE},
                )
            except Exception:  # noqa: BLE001
                pass
            logger.warning(
                "upbit_notice_collect_unexpected",
                error=result.last_error,
            )
        finally:
            if self._owns_client:
                await client.aclose()
        return result

    async def _collect_into(
        self,
        result: CollectorRunResult,
        client: UpbitNoticeClient,
        *,
        fetch_bodies: bool | None,
    ) -> None:
        if fetch_bodies is None:
            fetch_bodies = bool(
                getattr(self._settings, "upbit_notice_fetch_body", True)
            )
        per_page = max(
            1,
            min(int(getattr(self._settings, "upbit_notice_page_size", 20)), 50),
        )
        max_pages = max(
            1,
            min(int(getattr(self._settings, "upbit_notice_max_pages", 3)), 10),
        )
        overlap_hours = float(
            getattr(self._settings, "upbit_notice_collection_overlap_hours", 48.0)
        )

        before_dt: datetime | None = None
        latest = self._repository.latest_published_at(
            source_code=SOURCE_CODE_UPBIT_NOTICE
        )
        cutoff: datetime | None = None
        if isinstance(latest, datetime):
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            before_dt = latest
            cutoff = latest - timedelta(hours=overlap_hours)
            result.cursor_published_at = latest.isoformat()
            result.published_at_before = latest.isoformat()

        seen_ids: set[str] = set()
        notices: list[dict[str, Any]] = []

        for page in range(1, max_pages + 1):
            body = await client.list_announcements(
                page=page,
                per_page=per_page,
                category="all",
            )
            data = body.get("data") if isinstance(body, dict) else None
            page_items = []
            if isinstance(data, dict):
                page_items.extend(data.get("notices") or [])
                # 고정 공지는 1페이지만
                if page == 1:
                    page_items.extend(data.get("fixed_notices") or [])

            if not page_items:
                break

            page_min_listed: datetime | None = None
            for item in page_items:
                if not isinstance(item, dict):
                    result.parse_failure_count += 1
                    continue
                nid = item.get("id")
                if nid is None:
                    result.parse_failure_count += 1
                    continue
                external_id = str(nid)
                if external_id in seen_ids:
                    continue
                seen_ids.add(external_id)
                listed = parse_datetime_to_utc(item.get("listed_at"))
                if listed is not None:
                    if page_min_listed is None or listed < page_min_listed:
                        page_min_listed = listed
                notices.append(item)

            result.fetched_count = len(notices)
            # overlap window 밖이면 추가 페이지 중단
            if cutoff is not None and page_min_listed is not None:
                if page_min_listed < cutoff and page > 1:
                    break

        for item in notices:
            try:
                stored = await self._normalize_and_store(
                    client,
                    item,
                    fetch_bodies=fetch_bodies,
                )
            except Exception as exc:  # noqa: BLE001
                result.parse_failure_count += 1
                logger.info(
                    "upbit_notice_item_parse_failed",
                    error=str(exc)[:200],
                    notice_id=item.get("id"),
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

            if len(result.samples) < 5:
                result.samples.append(
                    {
                        "external_id": stored["external_id"],
                        "title": stored["title"],
                        "category": stored["category"],
                        "url": stored["url"],
                        "published_at": stored["published_at"],
                        "action": action,
                    }
                )

        # last_check와 별개로 "새 기사 존재 여부" 증명을 위한 스냅샷
        # - duplicates only면 published_at_after == published_at_before
        # - new insert면 published_at_after가 앞선 published_at_before보다 최신
        after_latest = self._repository.latest_published_at(
            source_code=SOURCE_CODE_UPBIT_NOTICE
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
            # 예외 케이스(저장소 latest_published_at가 반환 불능) — conservative
            result.last_new_article_at = result.published_at_before

    async def _normalize_and_store(
        self,
        client: UpbitNoticeClient,
        item: dict[str, Any],
        *,
        fetch_bodies: bool,
    ) -> dict[str, Any] | None:
        external_id = str(item.get("id") or "").strip()
        if not external_id:
            return None

        title = normalize_title(str(item.get("title") or ""))
        if not title:
            return None

        source_category = str(item.get("category") or "").strip() or None
        category = normalize_notice_category(
            source_category=source_category,
            title=title,
        )

        public_url = NOTICE_PUBLIC_URL_TEMPLATE.format(notice_id=external_id)
        canonical = canonicalize_url(public_url) or public_url

        published_at = parse_datetime_to_utc(item.get("listed_at"))
        first_listed = parse_datetime_to_utc(item.get("first_listed_at"))
        collected_at = datetime.now(timezone.utc)

        body_text = ""
        detail_meta: dict[str, Any] = {}
        if fetch_bodies:
            try:
                detail = await client.get_announcement(external_id)
                detail_data = detail.get("data") if isinstance(detail, dict) else None
                if isinstance(detail_data, dict):
                    body_text = strip_html(str(detail_data.get("body") or ""))
                    # list 메타보다 detail 우선
                    if detail_data.get("listed_at"):
                        published_at = (
                            parse_datetime_to_utc(detail_data.get("listed_at"))
                            or published_at
                        )
                    detail_meta = {
                        "need_new_badge": detail_data.get("need_new_badge"),
                        "need_update_badge": detail_data.get(
                            "need_update_badge"
                        ),
                        "uuid": detail_data.get("uuid"),
                    }
            except UpbitNoticeClientError as exc:
                # 목록 메타만으로도 저장 — body 실패는 item 실패로 치지 않음
                detail_meta = {"body_fetch_error": str(exc)[:200]}

        # 본문 대용량 방지 — description 은 요약 텍스트, raw 는 제한 길이
        max_body = int(
            getattr(self._settings, "upbit_notice_max_body_chars", 20_000)
        )
        normalized_text = body_text[:max_body] if body_text else title
        fingerprint = body_fingerprint(normalized_text)
        content_hash = identity_content_hash(
            source_code=SOURCE_CODE_UPBIT_NOTICE,
            external_id=external_id,
        )

        status = STATUS_ACTIVE
        existing = self._repository.find_by_content_hash(content_hash)
        if existing is not None:
            prev = existing.raw_data or {}
            prev_fp = prev.get("body_fingerprint") if isinstance(prev, dict) else None
            if prev_fp and prev_fp != fingerprint:
                status = STATUS_UPDATED

        raw_data: dict[str, Any] = {
            "source_type": SOURCE_TYPE_UPBIT_NOTICE,
            "external_id": external_id,
            "uuid": str(item.get("uuid") or detail_meta.get("uuid") or ""),
            "canonical_url": canonical,
            "category": category,
            "source_category": source_category,
            "language": LANGUAGE_KO,
            "status": status,
            "collected_at": collected_at.isoformat(),
            "updated_at": collected_at.isoformat(),
            "first_listed_at": (
                first_listed.isoformat() if first_listed else None
            ),
            "body_fingerprint": fingerprint,
            "list_item": {
                "need_new_badge": item.get("need_new_badge"),
                "need_update_badge": item.get("need_update_badge"),
            },
            **{k: v for k, v in detail_meta.items() if k != "uuid"},
        }
        # 원문 확인용 — 제한된 body만
        if body_text:
            raw_data["normalized_text"] = normalized_text

        row = {
            "exchange_code": PLACEHOLDER_EXCHANGE_UPBIT,
            "symbol": PLACEHOLDER_SYMBOL_NOTICE,
            "query_text": SOURCE_CODE_UPBIT_NOTICE,
            "title": title,
            "description": normalized_text[:4000] if normalized_text else None,
            "original_link": canonical,
            "naver_link": None,
            "published_at": published_at,
            "source_code": SOURCE_CODE_UPBIT_NOTICE,
            "content_hash": content_hash,
            "raw_data": raw_data,
        }

        action = self._repository.upsert_collector_article(row)
        return {
            "action": action,
            "external_id": external_id,
            "title": title,
            "category": category,
            "url": canonical,
            "published_at": published_at.isoformat() if published_at else None,
        }
