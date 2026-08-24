"""Dual LLM role wiring — unit/API focused tests (no REAL mutate)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stock_platform.api.v1.admin_upbit_dual_llm import router as dual_router
from stock_platform.operation.upbit_market_context.dual_llm_shadow_outcomes import (
    promotion_status,
)
from stock_platform.operation.upbit_market_context.schemas import (
    LlmContextInput,
    LlmContextOutput,
)


def test_promotion_gates() -> None:
    assert promotion_status(0)["promotion_status"] == "COLLECTION_ONLY"
    assert promotion_status(50)["promotion_status"] == "COLLECTION_ONLY"
    assert promotion_status(100)["promotion_status"] == "RESEARCH_ONLY"
    assert promotion_status(499)["promotion_status"] == "RESEARCH_ONLY"
    assert promotion_status(500)["promotion_status"] == "PROMOTION_REVIEW_ELIGIBLE"
    assert promotion_status(500)["auto_promote"] is False


def test_trading_shadow_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_platform.operation.upbit_market_context import trading_llm_shadow as tls

    monkeypatch.setattr(tls, "dual_llm_enabled", lambda: True)
    monkeypatch.setattr(tls, "trading_shadow_enabled", lambda: True)

    def _fail(**_k):
        return {
            "ok": False,
            "timeout": True,
            "error": "TIMEOUT",
            "latency_ms": 90000,
            "model": "qwen3.5:2b",
            "model_role": "TRADING",
            "parsed": None,
        }

    monkeypatch.setattr(tls, "chat_json_sync", _fail)
    inp = LlmContextInput(
        context_as_of="2026-08-24T00:00:00+00:00",
        candidate={"symbol": "KRW-BTC"},
    )
    out = tls.run_trading_llm_shadow(inp, analysis_summary={"market_summary": "x"})
    assert out["ok"] is False
    assert out["fallback_to_heuristic"] is True
    assert out["affects_real"] is False
    assert out["mode"] == "SHADOW"


def test_analysis_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_platform.operation.upbit_market_context import analysis_llm_service as als

    monkeypatch.setattr(als, "dual_llm_enabled", lambda: True)
    calls = {"n": 0}

    def _ok(**_k):
        calls["n"] += 1
        return {
            "ok": True,
            "timeout": False,
            "error": None,
            "latency_ms": 10,
            "model": "qwen3:1.7b",
            "model_role": "ANALYSIS",
            "parsed": {
                "market_summary": "시장 약세",
                "asset_summary": "BTC",
                "news_summary": "없음",
                "risk_factors": ["MARKET_WEAK"],
                "confidence": 0.5,
                "tone": "CAUTION",
            },
        }

    monkeypatch.setattr(als, "chat_json_sync", _ok)
    # clear cache between tests
    als.analysis_cache._data.clear()
    inp = LlmContextInput(
        context_as_of="2026-08-24T12:00:00+00:00",
        candidate={"symbol": "KRW-BTC"},
        market_context={"fear_greed": {"value_json": {"value": 40}}},
    )
    a = als.run_analysis_llm(inp, symbol="KRW-BTC")
    b = als.run_analysis_llm(inp, symbol="KRW-BTC")
    assert a["ok"] is True
    assert b.get("cache_hit") is True
    assert calls["n"] == 1


def test_candidate_keeps_heuristic_recommendation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from stock_platform.operation.upbit_market_context import candidate_llm as cl

    row = SimpleNamespace(
        shadow_id=101,
        symbol="KRW-TEST",
        recommendation="ALLOW",
        scanner_score=70,
        scanner_rank=1,
        ma5=1,
        ma20=1,
        rsi14=50,
        macd=0,
        atr14=1,
        volume_surge=1.0,
        trend=None,
        momentum=None,
        volatility=None,
        detected_at=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc),
        entry_snapshot={"candidate": {"symbol": "KRW-TEST", "recommendation": "ALLOW"}},
    )

    heur = LlmContextOutput(
        recommendation="HOLD",
        confidence=0.4,
        entry_quality_score=50,
        risk_flags=[],
        short_reason_ko="heuristic",
    )

    class FakeSvc:
        def build_llm_input(self, **_k):
            return (
                LlmContextInput(
                    context_as_of="2026-08-24T00:00:00+00:00",
                    candidate={"symbol": "KRW-TEST"},
                ),
                {"alignment": {"ok": True}},
            )

        def save_llm_analysis(self, **kwargs):
            ent = SimpleNamespace(
                analysis_id=9,
                input_json=kwargs["inp"].model_dump(),
                output_json=kwargs["out"].model_dump(),
            )
            self.last = ent
            return ent

    fake = FakeSvc()
    monkeypatch.setattr(
        cl,
        "MarketContextSnapshotService",
        lambda _s: fake,
    )
    monkeypatch.setattr(cl, "heuristic_llm_analyze", lambda _i: heur)

    import stock_platform.operation.upbit_market_context.analysis_llm_service as als
    import stock_platform.operation.upbit_market_context.trading_llm_shadow as tls

    monkeypatch.setattr(
        als,
        "run_analysis_llm",
        lambda *_a, **_k: {
            "ok": True,
            "model": "qwen3:1.7b",
            "model_role": "ANALYSIS",
            "market_summary": "ok",
            "asset_summary": "ok",
            "news_summary": "ok",
            "risk_factors": [],
            "confidence": 0.5,
            "latency_ms": 1,
        },
    )
    monkeypatch.setattr(
        tls,
        "run_trading_llm_shadow",
        lambda *_a, **_k: {
            "ok": True,
            "mode": "SHADOW",
            "affects_real": False,
            "model": "qwen3.5:2b",
            "recommendation": "REDUCE",
            "entry_quality_score": 30,
            "early_dump_risk": "HIGH",
            "confidence": 0.7,
            "risk_flags": ["OVERHEATED"],
            "reason_codes": ["SPIKE"],
            "latency_ms": 2,
        },
    )

    session = MagicMock()
    session.scalar = MagicMock(return_value=None)
    session.flush = MagicMock()

    # patch imports inside function via module-level after import path
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.analysis_llm_service.run_analysis_llm",
        lambda *_a, **_k: {
            "ok": True,
            "model": "qwen3:1.7b",
            "model_role": "ANALYSIS",
            "market_summary": "ok",
            "asset_summary": "ok",
            "news_summary": "ok",
            "risk_factors": [],
            "confidence": 0.5,
            "latency_ms": 1,
        },
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.trading_llm_shadow.run_trading_llm_shadow",
        lambda *_a, **_k: {
            "ok": True,
            "mode": "SHADOW",
            "affects_real": False,
            "model": "qwen3.5:2b",
            "recommendation": "REDUCE",
            "entry_quality_score": 30,
            "early_dump_risk": "HIGH",
            "confidence": 0.7,
            "risk_flags": ["OVERHEATED"],
            "reason_codes": ["SPIKE"],
            "latency_ms": 2,
        },
    )

    out = cl.maybe_analyze_shadow_candidate(session, row)
    assert out["ok"] is True
    assert out["REAL_POLICY_CHANGED"] == "NO"
    assert out["heuristic_recommendation"] == "HOLD"
    assert out["trading_shadow_recommendation"] == "REDUCE"
    # stored top-level recommendation stays heuristic
    assert fake.last.output_json["current_heuristic"]["recommendation"] == "HOLD"
    assert fake.last.output_json["trading_llm_shadow"]["recommendation"] == "REDUCE"
    assert fake.last.output_json["trading_llm_shadow"]["affects_real"] is False
    # Scanner row recommendation untouched
    assert row.recommendation == "ALLOW"


def test_dual_llm_status_route(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(dual_router)

    async def _admin():
        return {"role": "ADMIN"}

    from stock_platform.api.deps_admin import require_admin
    from stock_platform.database.session import get_db_session

    app.dependency_overrides[require_admin] = _admin
    app.dependency_overrides[get_db_session] = lambda: MagicMock()

    monkeypatch.setattr(
        "stock_platform.api.v1.admin_upbit_dual_llm.assign_clean_forward_obs",
        lambda _rows: [],
    )
    client = TestClient(app)
    res = client.get("/api/v1/admin/upbit/dual-llm/status")
    assert res.status_code == 200
    body = res.json()
    assert body["TRADING_LLM_MODE"] == "SHADOW"
    assert body["PROTECTIVE_EXIT_LLM_DEPENDENCY"] is False
    assert body["REAL_ORDER_MUTATION"] == 0
