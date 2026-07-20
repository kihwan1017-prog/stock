"""STEP69 — 관심종목 공시·AI 요약 계약 테스트."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.api.router import collect_duplicate_operation_ids
from stock_platform.disclosure.disclosure_ai_summary_service import (
    DisclosureAiRateLimitError,
    DisclosureAiSummaryService,
    DisclosureSummaryPayload,
)
from stock_platform.disclosure.user_disclosure_service import (
    UserDisclosureError,
    UserDisclosureService,
)
from stock_platform.scheduler.factory import build_job_registry


def test_user_disclosures_openapi_registered() -> None:
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/user/disclosures" in paths
    assert "/api/v1/user/disclosures/unread-count" in paths
    assert "/api/v1/user/disclosures/{disclosure_id}" in paths
    assert "/api/v1/user/disclosures/{disclosure_id}/ai-summary" in paths
    assert (
        "/api/v1/user/disclosures/{disclosure_id}/ai-summary/regenerate"
        in paths
    )
    assert "/api/v1/user/ai/status" in paths
    assert collect_duplicate_operation_ids(app.router) == []


def test_user_disclosures_requires_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/user/disclosures").status_code == 401
    assert client.get("/api/v1/user/disclosures/unread-count").status_code == 401
    assert client.post("/api/v1/user/disclosures/1/ai-summary").status_code == 401
    assert client.get("/api/v1/user/ai/status").status_code == 401


def test_watchlist_disclosure_sync_job_registered() -> None:
    registry = build_job_registry(MagicMock())
    names = {job.name for job in registry.list_jobs()}
    assert "watchlist_disclosure_sync" in names


def _watch_row(
    *,
    symbol: str = "005930",
    name: str = "삼성전자",
    disclosure_enabled: bool = True,
    market: str = "KRX",
    watchlist_id: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        market=market,
        symbol=symbol,
        symbol_name=name,
        disclosure_enabled=disclosure_enabled,
        watchlist_id=watchlist_id,
    )


def _disclosure(
    *,
    disclosure_id: int = 10,
    symbol: str = "005930",
) -> SimpleNamespace:
    return SimpleNamespace(
        disclosure_id=disclosure_id,
        receipt_no="20260719000123",
        corp_code="00126380",
        corp_name="삼성전자",
        stock_code=symbol,
        report_name="주요사항보고서",
        filer_name="삼성전자",
        receipt_date=date(2026, 7, 19),
        remark=None,
        category_code="MAJOR_EVENT",
        importance_score=80,
        is_correction=False,
        related_receipt_no=None,
    )


def test_list_empty_watchlist(monkeypatch: pytest.MonkeyPatch) -> None:
    service = UserDisclosureService(MagicMock())
    monkeypatch.setattr(service._watchlist, "list_for_user", lambda _uid: [])
    result = service.list_disclosures(1)
    assert result["watchlist_empty"] is True
    assert result["items"] == []


def test_list_rejects_non_watchlist_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = UserDisclosureService(MagicMock())
    monkeypatch.setattr(
        service._watchlist,
        "list_for_user",
        lambda _uid: [_watch_row()],
    )
    with pytest.raises(UserDisclosureError, match="관심종목"):
        service.list_disclosures(1, symbol="000660")


def test_detail_rejects_unrelated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = UserDisclosureService(MagicMock())
    monkeypatch.setattr(
        service._watchlist,
        "list_for_user",
        lambda _uid: [_watch_row()],
    )
    monkeypatch.setattr(
        service._repo,
        "get_disclosure",
        lambda _id: _disclosure(symbol="999999"),
    )
    with pytest.raises(UserDisclosureError, match="연결되지 않은"):
        service.get_detail(1, 10)


def test_ai_summary_reuses_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    session = MagicMock()
    service = DisclosureAiSummaryService(session)
    disclosure = _disclosure()
    cached = SimpleNamespace(
        disclosure_id=10,
        status="COMPLETED",
        summary_text="요약",
        key_points_json=["a"],
        risk_factors_json=[],
        financial_impacts_json=[],
        important_numbers_json=[],
        uncertainty_notes_json=[],
        model_name="qwen3.5:4b",
        prompt_version="v1",
        generated_at=None,
        error_code=None,
    )
    monkeypatch.setattr(
        service._user,
        "get_detail",
        lambda *_a, **_k: {"disclosure_id": 10},
    )
    monkeypatch.setattr(
        service._repo, "get_disclosure", lambda _id: disclosure
    )
    monkeypatch.setattr(
        service._repo, "find_summary_cache", lambda **_k: cached
    )
    monkeypatch.setattr(service, "_check_rate_limit", lambda *_a: None)

    result = asyncio.run(service.request_summary(1, 10, regenerate=False))
    assert result["status"] == "COMPLETED"
    assert result["summary"] == "요약"


def test_ai_summary_schema_validation() -> None:
    payload = DisclosureSummaryPayload.model_validate(
        {
            "summary": "ok",
            "key_points": ["a"],
            "risk_factors": [],
            "financial_impacts": [],
            "important_numbers": [],
            "uncertainty_notes": ["unknown"],
        }
    )
    assert payload.summary == "ok"


def test_rate_limit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    service = DisclosureAiSummaryService(MagicMock())
    monkeypatch.setattr(
        service._settings,
        "ai_disclosure_summary_cooldown_seconds",
        60,
    )
    # 첫 요청 기록
    service._check_rate_limit(99, 1)
    with pytest.raises(DisclosureAiRateLimitError):
        service._check_rate_limit(99, 1)


def test_availability_without_admin_permission() -> None:
    service = DisclosureAiSummaryService(MagicMock())
    result = service.availability()
    assert "disclosure_summary_available" in result
    assert "base_url" not in result
    assert "host" not in result
