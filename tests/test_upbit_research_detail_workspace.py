"""Upbit research detail workspace — READ APIs focused tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stock_platform.api.v1.admin_upbit_research import router as research_router
from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
    CLEAN_FORWARD_EPOCH_START,
    classify_forward_row,
)
from stock_platform.operation.upbit_market_context import research_detail_workspace as rdw


def _admin_app() -> FastAPI:
    app = FastAPI()
    app.include_router(research_router)

    async def _admin():
        return {"role": "ADMIN"}

    from stock_platform.api.deps_admin import require_admin

    app.dependency_overrides[require_admin] = _admin
    return app


def _clean_row(**overrides: object) -> SimpleNamespace:
    det = CLEAN_FORWARD_EPOCH_START + timedelta(hours=2)
    base = {
        "shadow_id": 9001,
        "scanner_run_id": "run-clean-1",
        "symbol": "KRW-TEST",
        "recommendation": "ALLOW",
        "status": "COMPLETED",
        "scanner_rank": 1,
        "scanner_score": 0.9,
        "entry_price": 1000.0,
        "confidence": 0.8,
        "ma5": 101.0,
        "ma20": 100.0,
        "rsi14": 55.0,
        "macd": 0.1,
        "atr14": 1.0,
        "volume_surge": 1.5,
        "trade_value_24h": 1e9,
        "detected_at": det,
        "created_at": det,
        "completed_at": det + timedelta(hours=1),
        "return_5m_pct": 0.1,
        "return_15m_pct": 0.2,
        "return_30m_pct": -0.1,
        "return_60m_pct": 0.05,
        "mfe_pct": 0.5,
        "mae_pct": -0.3,
        "entry_snapshot": {
            "entry_price_provenance": {
                "ok": True,
                "quality": "CANONICAL",
                "source": "market.candle_minute",
            },
            "candidate": {"symbol": "KRW-TEST", "score": 0.9, "recommendation": "ALLOW"},
        },
        "evaluation_detail": {
            "exit_ab": {"baseline": {"net_pnl_krw": 10}},
            "entry_ab": {"outcome": {"net_pnl_krw": 10}},
            "entry_forward_features": {"ok": True, "return_3m": 0.01},
            "windows": {
                "5": {"status": "OK", "price": 1001, "return_pct": 0.1},
                "15": {"status": "OK", "price": 1002, "return_pct": 0.2},
                "30": {"status": "OK", "price": 999, "return_pct": -0.1},
                "60": {"status": "OK", "price": 1000.5, "return_pct": 0.05},
            },
        },
        "deleted_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_research_routes_registered() -> None:
    paths = [getattr(r, "path", "") for r in research_router.routes]
    assert any("/clean-forward" in (p or "") for p in paths)
    assert any("/market-context" in (p or "") for p in paths)
    assert any("/experiments" in (p or "") for p in paths)


def test_classify_excludes_legacy_and_backfill() -> None:
    legacy = _clean_row(
        shadow_id=1,
        detected_at=CLEAN_FORWARD_EPOCH_START - timedelta(days=1),
        created_at=CLEAN_FORWARD_EPOCH_START - timedelta(days=1),
    )
    assert classify_forward_row(legacy)["clean"] is False
    assert classify_forward_row(legacy)["cohort"] != "CLEAN_FORWARD"

    backfill = _clean_row(
        shadow_id=2,
        evaluation_detail={
            **_clean_row().evaluation_detail,
            "research_stamp_backfill": {"stamped_at": "2026-08-24T00:00:00Z"},
        },
    )
    cls = classify_forward_row(backfill)
    assert cls["clean"] is False
    assert cls["cohort"] == "STAMPED_BACKFILL_ONLY"

    clean = _clean_row()
    assert classify_forward_row(clean)["clean"] is True


def test_list_clean_forward_pagination_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        _clean_row(shadow_id=i, symbol=f"KRW-T{i}", recommendation="ALLOW" if i % 2 else "REDUCE")
        for i in range(1, 6)
    ]
    # inject one legacy
    rows.append(
        _clean_row(
            shadow_id=99,
            symbol="KRW-LEG",
            detected_at=CLEAN_FORWARD_EPOCH_START - timedelta(days=2),
            created_at=CLEAN_FORWARD_EPOCH_START - timedelta(days=2),
        )
    )

    monkeypatch.setattr(rdw, "load_completed_shadows", lambda _s: rows)
    session = MagicMock()
    out = rdw.list_clean_forward(session, page=1, page_size=2, recommendation="ALLOW")
    assert out["page_size"] == 2
    assert out["page"] == 1
    assert out["legacy_excluded"] is True
    assert out["backfill_excluded"] is True
    # only ALLOW clean rows
    assert all(i["ai_recommendation"] == "ALLOW" for i in out["items"])
    assert out["total"] == sum(1 for r in rows if classify_forward_row(r).get("clean") and r.recommendation == "ALLOW")
    assert len(out["items"]) <= 2


def test_clean_detail_excludes_future_news(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _clean_row()
    session = MagicMock()

    monkeypatch.setattr(
        rdw,
        "load_completed_shadows",
        lambda _s: [row],
    )

    session.scalar = MagicMock(return_value=row)

    def _fake_news(*_a, **_k):
        return {
            "items": [
                {
                    "article_id": 1,
                    "published_at": "before",
                    "lookahead_ok": True,
                }
            ],
            "lookahead_protected": True,
            "cutoff": "x",
            "note_ko": "ok",
            "relation_confidence": "BEST_EFFORT",
        }

    monkeypatch.setattr(rdw, "_news_before", _fake_news)
    monkeypatch.setattr(
        rdw,
        "_market_as_of_bundle",
        lambda *_a, **_k: {"relation_confidence": "BEST_EFFORT", "ok": True},
    )
    monkeypatch.setattr(
        rdw,
        "_llm_for_shadow",
        lambda *_a, **_k: {
            "found": False,
            "relation_confidence": "NONE",
            "empty_hint_ko": "신규 Scanner Shadow 후보 발생 시 분석됩니다.",
            "analysis": None,
        },
    )

    detail = rdw.get_clean_forward_detail(session, shadow_id=9001)
    assert detail is not None
    assert detail["lookahead_sections_separated"] is True
    assert detail["at_entry"]["news_notice"]["lookahead_protected"] is True
    assert "forward_outcome" in detail
    assert "at_entry" in detail


def test_clean_detail_404_for_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = _clean_row(
        shadow_id=7,
        detected_at=CLEAN_FORWARD_EPOCH_START - timedelta(days=3),
        created_at=CLEAN_FORWARD_EPOCH_START - timedelta(days=3),
    )
    session = MagicMock()
    session.scalar = MagicMock(return_value=legacy)
    assert rdw.get_clean_forward_detail(session, shadow_id=7) is None


def test_api_clean_forward_200(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _admin_app()

    def _fake_list(*_a, **_k):
        return {
            "schema": "upbit_research_clean_forward_list_v1",
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 20,
            "legacy_excluded": True,
            "backfill_excluded": True,
        }

    monkeypatch.setattr(rdw, "list_clean_forward", _fake_list)
    from stock_platform.database.session import get_db_session

    app.dependency_overrides[get_db_session] = lambda: MagicMock()
    client = TestClient(app)
    res = client.get("/api/v1/admin/upbit/research/clean-forward?page=1&page_size=20")
    assert res.status_code == 200
    assert res.json()["total"] == 0


def test_api_experiments_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _admin_app()

    def _fake_exp(_s):
        return {
            "schema": "upbit_research_filter_experiments_v1",
            "clean_sample_count": 37,
            "under_promotion_sample": True,
            "warning_ko": "연구 표본 수집 중 — REAL 전략 승격 근거로 사용할 수 없습니다.",
            "best_filter_label_ko": "현재 연구 후보",
            "arms": [{"experiment": "E0", "accepted": 37}],
            "legacy_excluded": True,
            "backfill_excluded": True,
        }

    monkeypatch.setattr(rdw, "get_filter_experiments", _fake_exp)
    from stock_platform.database.session import get_db_session

    app.dependency_overrides[get_db_session] = lambda: MagicMock()
    client = TestClient(app)
    res = client.get("/api/v1/admin/upbit/research/experiments")
    assert res.status_code == 200
    body = res.json()
    assert body["under_promotion_sample"] is True
    assert "승격 근거" in (body.get("warning_ko") or "")
