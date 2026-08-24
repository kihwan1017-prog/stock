"""STEP N2 — UPBIT News/Notice Collector focused tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from stock_platform.news.collector_category import normalize_notice_category
from stock_platform.news.collector_constants import (
    CATEGORY_CAUTION,
    CATEGORY_DEPOSIT_WITHDRAWAL,
    CATEGORY_GENERAL,
    CATEGORY_LISTING,
    CATEGORY_MAINTENANCE,
    SOURCE_CODE_UPBIT_NOTICE,
)
from stock_platform.news.collector_normalize import (
    canonicalize_url,
    identity_content_hash,
    normalize_title,
    parse_datetime_to_utc,
    strip_html,
)
from stock_platform.news.collector_scheduler import (
    UpbitNewsNoticeCollectorScheduler,
)
from stock_platform.news.crypto_news_collector import (
    resolve_crypto_news_provider,
)
from stock_platform.news.upbit_notice_collector import UpbitNoticeCollector


def test_upbit_notice_category_normalization() -> None:
    assert (
        normalize_notice_category(
            source_category="입출금",
            title="BTC 입출금 일시 중단",
        )
        == CATEGORY_DEPOSIT_WITHDRAWAL
    )
    assert (
        normalize_notice_category(
            source_category="안내",
            title="OO KRW 마켓 디지털 자산 추가",
        )
        == CATEGORY_LISTING
    )
    assert (
        normalize_notice_category(
            source_category="안내",
            title="네트워크 점검 안내",
        )
        == CATEGORY_MAINTENANCE
    )
    assert (
        normalize_notice_category(
            source_category="안내",
            title="유의 종목 지정 안내",
        )
        == CATEGORY_CAUTION
    )
    assert (
        normalize_notice_category(source_category="???", title="기타 안내")
        == CATEGORY_GENERAL
    )


def test_published_at_normalize_to_utc() -> None:
    dt = parse_datetime_to_utc("2026-08-13T21:10:07+09:00")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0
    assert dt.hour == 12  # KST 21:10 → UTC 12:10


def test_url_canonicalize() -> None:
    url = canonicalize_url(
        "https://www.Upbit.com/service_center/notice?id=6439&utm_source=x"
    )
    assert url == "https://www.upbit.com/service_center/notice?id=6439"


def test_html_text_normalize() -> None:
    assert strip_html("<b>Hello</b>  &amp;  world") == "Hello & world"
    assert normalize_title("  공지\n제목  ") == "공지 제목"


def test_identity_hash_stable_for_external_id() -> None:
    a = identity_content_hash(source_code=SOURCE_CODE_UPBIT_NOTICE, external_id="6439")
    b = identity_content_hash(source_code=SOURCE_CODE_UPBIT_NOTICE, external_id="6439")
    c = identity_content_hash(source_code=SOURCE_CODE_UPBIT_NOTICE, external_id="9999")
    assert a == b
    assert a != c


@pytest.mark.asyncio
async def test_duplicate_collection_idempotent() -> None:
    """동일 external_id 재수집 → duplicate/updated, row 중복 없음."""

    repo = MagicMock()
    repo.latest_published_at.return_value = None
    repo.find_by_content_hash.return_value = None
    repo.upsert_collector_article.side_effect = ["inserted", "duplicate"]

    client = MagicMock()
    client.list_announcements = AsyncMock(
        return_value={
            "success": True,
            "data": {
                "notices": [
                    {
                        "id": 100,
                        "uuid": "u100",
                        "title": "테스트 공지",
                        "category": "안내",
                        "listed_at": "2026-08-13T12:00:00+09:00",
                        "first_listed_at": "2026-08-13T12:00:00+09:00",
                    }
                ],
                "fixed_notices": [],
            },
        }
    )
    client.get_announcement = AsyncMock(
        return_value={
            "success": True,
            "data": {
                "id": 100,
                "title": "테스트 공지",
                "category": "안내",
                "listed_at": "2026-08-13T12:00:00+09:00",
                "body": "<p>본문</p>",
            },
        }
    )
    client.aclose = AsyncMock()

    session = MagicMock()
    settings = SimpleNamespace(
        upbit_notice_fetch_body=True,
        upbit_notice_page_size=20,
        upbit_notice_max_pages=1,
        upbit_notice_collection_overlap_hours=48.0,
        upbit_notice_max_body_chars=20000,
    )

    collector = UpbitNoticeCollector(
        session,
        client=client,
        settings=settings,
        repository=repo,
    )
    first = await collector.collect()
    assert first.inserted_count == 1
    assert first.fetched_count == 1

    repo.find_by_content_hash.return_value = SimpleNamespace(
        raw_data={"body_fingerprint": "x"}
    )
    second = await collector.collect()
    assert second.duplicate_count == 1
    assert second.inserted_count == 0


@pytest.mark.asyncio
async def test_edited_notice_update_policy() -> None:
    repo = MagicMock()
    repo.latest_published_at.return_value = None
    existing = SimpleNamespace(
        raw_data={"body_fingerprint": "oldfp", "external_id": "200"}
    )
    repo.find_by_content_hash.return_value = existing
    repo.upsert_collector_article.return_value = "updated"

    client = MagicMock()
    client.list_announcements = AsyncMock(
        return_value={
            "success": True,
            "data": {
                "notices": [
                    {
                        "id": 200,
                        "title": "수정된 공지",
                        "category": "입출금",
                        "listed_at": "2026-08-13T21:00:00+09:00",
                        "first_listed_at": "2026-08-01T10:00:00+09:00",
                    }
                ],
                "fixed_notices": [],
            },
        }
    )
    client.get_announcement = AsyncMock(
        return_value={
            "success": True,
            "data": {
                "id": 200,
                "title": "수정된 공지",
                "category": "입출금",
                "listed_at": "2026-08-13T21:00:00+09:00",
                "body": "업데이트된 본문",
            },
        }
    )
    client.aclose = AsyncMock()
    settings = SimpleNamespace(
        upbit_notice_fetch_body=True,
        upbit_notice_page_size=20,
        upbit_notice_max_pages=1,
        upbit_notice_collection_overlap_hours=48.0,
        upbit_notice_max_body_chars=20000,
    )
    collector = UpbitNoticeCollector(
        MagicMock(),
        client=client,
        settings=settings,
        repository=repo,
    )
    result = await collector.collect()
    assert result.updated_count == 1
    assert result.inserted_count == 0


@pytest.mark.asyncio
async def test_collector_retry_and_source_failure_isolation() -> None:
    """source 실패가 예외로 전파되지 않고 failure_count만 증가."""

    from stock_platform.news.upbit_notice_client import UpbitNoticeClientError

    repo = MagicMock()
    repo.latest_published_at.return_value = None
    client = MagicMock()
    client.list_announcements = AsyncMock(
        side_effect=UpbitNoticeClientError("boom")
    )
    client.aclose = AsyncMock()
    settings = SimpleNamespace(
        upbit_notice_fetch_body=False,
        upbit_notice_page_size=20,
        upbit_notice_max_pages=1,
        upbit_notice_collection_overlap_hours=48.0,
        upbit_notice_max_body_chars=20000,
    )
    collector = UpbitNoticeCollector(
        MagicMock(),
        client=client,
        settings=settings,
        repository=repo,
    )
    result = await collector.collect()
    assert result.failure_count == 1
    assert result.last_error is not None
    repo.record_failure.assert_called()


def test_scheduler_respects_env_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """env=false 이면 Job 미등록 (기본값이 ON이어도 env 우선)."""

    monkeypatch.setenv("UPBIT_NOTICE_COLLECTION_ENABLED", "false")
    monkeypatch.setenv("CRYPTO_NEWS_COLLECTION_ENABLED", "false")
    from stock_platform.common.settings import clear_settings_cache, get_settings

    clear_settings_cache()
    settings = get_settings()
    assert settings.upbit_notice_collection_enabled is False
    assert settings.crypto_news_collection_enabled is False

    sched = UpbitNewsNoticeCollectorScheduler()
    assert sched.notice_enabled() is False
    assert sched.crypto_enabled() is False
    status = sched.status()
    assert status["enabled"] is False
    assert status["running"] is False


def test_scheduler_registration_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UPBIT_NOTICE_COLLECTION_ENABLED", "true")
    monkeypatch.setenv("UPBIT_NOTICE_COLLECTION_INTERVAL_SECONDS", "300")
    monkeypatch.setenv("CRYPTO_NEWS_COLLECTION_ENABLED", "false")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    sched = UpbitNewsNoticeCollectorScheduler()
    sched.configure(force=True)
    job = sched._scheduler.get_job(sched.NOTICE_JOB_ID)
    assert job is not None
    crypto_job = sched._scheduler.get_job(sched.CRYPTO_JOB_ID)
    assert crypto_job is None


def test_crypto_provider_status_without_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NAVER_CLIENT_ID", "")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    status = resolve_crypto_news_provider()
    assert status.available is False
    assert status.provider == "NEWS_PROVIDER_NOT_AVAILABLE"


def test_no_symbol_mapping_in_store_row() -> None:
    """placeholder symbol only — trading symbol 매핑 필드 없음."""

    from stock_platform.news.collector_constants import (
        PLACEHOLDER_SYMBOL_NOTICE,
    )

    assert PLACEHOLDER_SYMBOL_NOTICE.startswith("_")
    assert "BTC" not in PLACEHOLDER_SYMBOL_NOTICE


def test_collector_modules_have_no_ai_or_scanner_imports() -> None:
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "stock_platform" / "news"
    files = [
        root / "upbit_notice_collector.py",
        root / "crypto_news_collector.py",
        root / "collector_scheduler.py",
        root / "collector_category.py",
    ]
    banned = {
        "stock_platform.ai.ollama_client",
        "stock_platform.operation.upbit_opportunity_scanner",
        "stock_platform.operation.upbit_opportunity_shadow",
    }
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in banned, path.name
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in banned


def test_dedup_keys_cover_external_url_hash() -> None:
    h1 = identity_content_hash(
        source_code=SOURCE_CODE_UPBIT_NOTICE, external_id="1"
    )
    h2 = identity_content_hash(
        source_code=SOURCE_CODE_UPBIT_NOTICE, external_id="1"
    )
    assert h1 == h2
    url = canonicalize_url(
        "https://www.upbit.com/service_center/notice?id=1&utm_campaign=a"
    )
    assert url is not None
    assert "utm_" not in url
