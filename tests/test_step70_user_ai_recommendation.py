"""STEP70 — 사용자 AI 추천·권한 분리 계약 테스트."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.api.router import collect_duplicate_operation_ids
from stock_platform.ai.user_ai_recommendation_service import (
    RecommendationItemPayload,
    RecommendationResponsePayload,
    UserAiRateLimitError,
    UserAiRecommendationError,
    UserAiRecommendationService,
)


def test_user_ai_recommendation_openapi() -> None:
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/user/ai/status" in paths
    assert "/api/v1/user/ai/recommendations" in paths
    assert "/api/v1/user/ai/recommendations/latest" in paths
    assert "/api/v1/user/ai/recommendations/{request_id}" in paths
    assert (
        "/api/v1/user/ai/recommendations/{request_id}/bookmark" in paths
    )
    assert collect_duplicate_operation_ids(app.router) == []


def test_user_ai_requires_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/user/ai/status").status_code == 401
    assert client.get("/api/v1/user/ai/recommendations").status_code == 401
    assert client.post("/api/v1/user/ai/recommendations").status_code == 401


def test_status_hides_ollama_host() -> None:
    service = UserAiRecommendationService(MagicMock())
    payload = service.availability()
    assert "available" in payload
    assert "base_url" not in payload
    assert "host" not in payload
    assert "ollama" not in str(payload).lower() or "available" in payload


def test_resolve_candidates_watchlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = UserAiRecommendationService(MagicMock())
    monkeypatch.setattr(
        service._watchlist,
        "list_for_user",
        lambda _uid: [
            SimpleNamespace(
                market="KRX",
                symbol="005930",
                symbol_name="삼성전자",
                ai_enabled=True,
            ),
            SimpleNamespace(
                market="KRX",
                symbol="000660",
                symbol_name="SK하이닉스",
                ai_enabled=False,
            ),
        ],
    )
    rows = service.resolve_candidates(
        1,
        market_code="KRX",
        source_type="WATCHLIST",
        account_id=None,
    )
    assert len(rows) == 1
    assert rows[0]["symbol"] == "005930"


def test_validate_rejects_foreign_symbol() -> None:
    service = UserAiRecommendationService(MagicMock())
    with pytest.raises(UserAiRecommendationError, match="후보에 없는"):
        service._validate_items(
            [
                RecommendationItemPayload(
                    rank=1,
                    symbol="999999",
                    action="WATCH",
                    confidence_score=0.5,
                    total_score=50,
                    summary="x",
                    reasons=["a"],
                    risk_factors=["b"],
                )
            ],
            allowed={"005930"},
            name_map={"005930": "삼성전자"},
            recommendation_count=5,
            candidates=[{"symbol": "005930", "symbol_name": "삼성전자"}],
        )


def test_validate_rejects_duplicate_rank() -> None:
    service = UserAiRecommendationService(MagicMock())
    with pytest.raises(UserAiRecommendationError, match="rank 중복"):
        service._validate_items(
            [
                RecommendationItemPayload(
                    rank=1,
                    symbol="005930",
                    action="WATCH",
                    confidence_score=0.5,
                    total_score=50,
                    summary="x",
                    reasons=["a"],
                    risk_factors=["b"],
                ),
                RecommendationItemPayload(
                    rank=1,
                    symbol="000660",
                    action="NEUTRAL",
                    confidence_score=0.4,
                    total_score=40,
                    summary="y",
                    reasons=["a"],
                    risk_factors=["b"],
                ),
            ],
            allowed={"005930", "000660"},
            name_map={"005930": "a", "000660": "b"},
            recommendation_count=5,
            candidates=[
                {"symbol": "005930", "symbol_name": "a"},
                {"symbol": "000660", "symbol_name": "b"},
            ],
        )


def test_schema_payload_ok() -> None:
    payload = RecommendationResponsePayload.model_validate(
        {
            "items": [
                {
                    "rank": 1,
                    "symbol": "005930",
                    "action": "WATCH",
                    "confidence_score": 0.8,
                    "total_score": 80,
                    "summary": "요약",
                    "reasons": ["근거"],
                    "risk_factors": ["위험"],
                }
            ]
        }
    )
    assert payload.items[0].action == "WATCH"


def test_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    service = UserAiRecommendationService(MagicMock())
    monkeypatch.setattr(
        service._settings, "ai_recommendation_cooldown_seconds", 60
    )
    service._check_rate_limit(7, "hash-a")
    with pytest.raises(UserAiRateLimitError):
        service._check_rate_limit(7, "hash-a")


def test_invalid_source_type() -> None:
    service = UserAiRecommendationService(MagicMock())
    with pytest.raises(UserAiRecommendationError, match="source_type"):
        service.resolve_candidates(
            1,
            market_code="KRX",
            source_type="EVERYTHING",
            account_id=None,
        )
