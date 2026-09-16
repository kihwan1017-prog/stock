"""STEP68 — 관심종목 뉴스 API·서비스 계약 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.api.router import collect_duplicate_operation_ids
from stock_platform.news.user_news_service import UserNewsError, UserNewsService
from stock_platform.scheduler.factory import build_job_registry


def test_user_news_openapi_registered() -> None:
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/user/news" in paths
    assert "/api/v1/user/news/unread-count" in paths
    assert "/api/v1/user/news/read-all" in paths
    assert "/api/v1/user/news/{news_id}" in paths
    assert "/api/v1/user/news/{news_id}/read" in paths
    assert "/api/v1/user/news/{news_id}/bookmark" in paths
    assert collect_duplicate_operation_ids(app.router) == []


def test_user_news_requires_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/user/news").status_code == 401
    assert client.get("/api/v1/user/news/unread-count").status_code == 401
    assert client.post("/api/v1/user/news/read-all").status_code == 401
    assert client.get("/api/v1/user/news/1").status_code == 401
    assert client.post("/api/v1/user/news/1/read").status_code == 401
    assert client.post("/api/v1/user/news/1/bookmark").status_code == 401


def test_watchlist_news_sync_job_registered() -> None:
    registry = build_job_registry(MagicMock())
    names = {job.name for job in registry.list_jobs()}
    assert "watchlist_news_sync" in names


def _watch_row(
    *,
    market: str = "KRX",
    symbol: str = "005930",
    name: str = "삼성전자",
    news_enabled: bool = True,
    watchlist_id: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        market=market,
        symbol=symbol,
        symbol_name=name,
        news_enabled=news_enabled,
        watchlist_id=watchlist_id,
    )


def _article(
    *,
    article_id: int = 10,
    market: str = "KRX",
    symbol: str = "005930",
    title: str = "반도체 수출 증가",
) -> SimpleNamespace:
    return SimpleNamespace(
        article_id=article_id,
        exchange_code=market,
        symbol=symbol,
        title=title,
        description="요약",
        source_code="NAVER",
        original_link="https://example.com/a",
        naver_link="https://news.naver.com/a",
        published_at=datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc),
    )


def test_list_empty_watchlist(monkeypatch: pytest.MonkeyPatch) -> None:
    service = UserNewsService(MagicMock())
    monkeypatch.setattr(service._watchlist, "list_for_user", lambda _uid: [])
    result = service.list_news(1)
    assert result["watchlist_empty"] is True
    assert result["total_count"] == 0
    assert result["items"] == []


def test_list_rejects_non_watchlist_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = UserNewsService(MagicMock())
    monkeypatch.setattr(
        service._watchlist,
        "list_for_user",
        lambda _uid: [_watch_row()],
    )
    with pytest.raises(UserNewsError, match="관심종목"):
        service.list_news(1, symbol="000660")


def test_list_filters_news_enabled_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = UserNewsService(MagicMock())
    monkeypatch.setattr(
        service._watchlist,
        "list_for_user",
        lambda _uid: [
            _watch_row(news_enabled=False),
            _watch_row(
                symbol="000660",
                name="SK하이닉스",
                news_enabled=True,
                watchlist_id=2,
            ),
        ],
    )
    captured: dict = {}

    def fake_count(**kwargs):
        captured["pairs"] = kwargs["symbol_pairs"]
        return 0

    monkeypatch.setattr(service._news, "count_for_symbols", fake_count)
    monkeypatch.setattr(
        service._news,
        "list_for_symbols",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        service._news,
        "list_user_states",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        service._news,
        "list_symbol_links",
        lambda _ids: [],
    )
    result = service.list_news(1)
    assert captured["pairs"] == [("KRX", "000660")]
    assert result["watchlist_empty"] is False


def test_detail_rejects_unrelated_article(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = UserNewsService(MagicMock())
    monkeypatch.setattr(
        service._watchlist,
        "list_for_user",
        lambda _uid: [_watch_row()],
    )
    monkeypatch.setattr(
        service._news,
        "get_article",
        lambda _id: _article(symbol="999999"),
    )
    monkeypatch.setattr(
        service._news,
        "list_symbol_links",
        lambda _ids: [],
    )
    with pytest.raises(UserNewsError, match="연결되지 않은"):
        service.get_detail(1, 10)


def test_mark_read_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    service = UserNewsService(MagicMock())
    article = _article()
    state = SimpleNamespace(
        is_read=False,
        read_at=None,
        is_bookmarked=False,
        bookmarked_at=None,
        hidden_at=None,
    )
    monkeypatch.setattr(
        service._watchlist,
        "list_for_user",
        lambda _uid: [_watch_row()],
    )
    monkeypatch.setattr(service._news, "get_article", lambda _id: article)
    monkeypatch.setattr(
        service._news,
        "list_user_states",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        service._news,
        "list_symbol_links",
        lambda _ids: [],
    )
    monkeypatch.setattr(
        service._news,
        "get_or_create_user_state",
        lambda **_kwargs: state,
    )
    first = service.mark_read(1, 10, read=True)
    second = service.mark_read(1, 10, read=True)
    assert first["is_read"] is True
    assert second["is_read"] is True
    assert state.is_read is True


def test_mark_bookmark_and_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    service = UserNewsService(MagicMock())
    article = _article()
    state = SimpleNamespace(
        is_read=False,
        read_at=None,
        is_bookmarked=False,
        bookmarked_at=None,
        hidden_at=None,
    )
    monkeypatch.setattr(
        service._watchlist,
        "list_for_user",
        lambda _uid: [_watch_row()],
    )
    monkeypatch.setattr(service._news, "get_article", lambda _id: article)
    monkeypatch.setattr(
        service._news,
        "list_user_states",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        service._news,
        "list_symbol_links",
        lambda _ids: [],
    )
    monkeypatch.setattr(
        service._news,
        "get_or_create_user_state",
        lambda **_kwargs: state,
    )
    on = service.mark_bookmark(1, 10, bookmarked=True)
    off = service.mark_bookmark(1, 10, bookmarked=False)
    assert on["is_bookmarked"] is True
    assert off["is_bookmarked"] is False
    assert state.bookmarked_at is None


def test_unread_count_empty_watchlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = UserNewsService(MagicMock())
    monkeypatch.setattr(service._watchlist, "list_for_user", lambda _uid: [])
    result = service.unread_count(1)
    assert result["unread_count"] == 0
    assert result["by_symbol"] == []
