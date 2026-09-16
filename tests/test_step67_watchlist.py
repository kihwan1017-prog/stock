"""STEP67 — 관심종목 서비스·API 계약 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.api.router import collect_duplicate_operation_ids
from stock_platform.trading.watchlist_service import (
    MAX_WATCHLIST_ITEMS,
    WatchlistError,
    WatchlistService,
)


def test_watchlist_openapi_registered() -> None:
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/user/watchlist" in paths
    assert "/api/v1/user/watchlist/search" in paths
    assert "/api/v1/user/watchlist/{watchlist_id}" in paths
    assert "/api/v1/user/watchlist/reorder" in paths
    assert collect_duplicate_operation_ids(app.router) == []


def test_watchlist_requires_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/user/watchlist").status_code == 401
    assert (
        client.post(
            "/api/v1/user/watchlist",
            json={"market": "KRX", "symbol": "005930"},
        ).status_code
        == 401
    )
    assert client.get(
        "/api/v1/user/watchlist/search",
        params={"q": "삼성"},
    ).status_code == 401


def test_add_rejects_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    service = WatchlistService(session)
    existing = MagicMock()
    monkeypatch.setattr(
        service._repo,
        "count_for_user",
        lambda _uid: 1,
    )
    monkeypatch.setattr(
        service._repo,
        "find_by_symbol",
        lambda **_kwargs: existing,
    )
    with pytest.raises(WatchlistError, match="이미 등록"):
        service.add_item(1, market="KRX", symbol="005930")


def test_add_rejects_over_max(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    service = WatchlistService(session)
    monkeypatch.setattr(
        service._repo,
        "count_for_user",
        lambda _uid: MAX_WATCHLIST_ITEMS,
    )
    monkeypatch.setattr(
        service._repo,
        "find_by_symbol",
        lambda **_kwargs: None,
    )
    with pytest.raises(WatchlistError, match="최대"):
        service.add_item(1, market="KRX", symbol="005930")


def test_delete_foreign_item_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    service = WatchlistService(session)
    monkeypatch.setattr(
        service._repo,
        "get_owned",
        lambda **_kwargs: None,
    )
    with pytest.raises(WatchlistError, match="찾을 수 없"):
        service.delete_item(user_id=1, watchlist_id=99)


def test_reorder_rejects_foreign_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    service = WatchlistService(session)
    owned = MagicMock()
    owned.watchlist_id = 1
    owned.display_order = 1
    monkeypatch.setattr(
        service._repo,
        "list_for_user",
        lambda _uid: [owned],
    )
    with pytest.raises(WatchlistError, match="존재하지 않는"):
        service.reorder(1, [1, 999])
