"""UPBIT + KIWOOM Dual LLM RAG market isolation tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.dual_llm.markets import (
    MARKET_KIWOOM,
    MARKET_UPBIT,
    same_market,
)
from stock_platform.operation.dual_llm.prompt_versions import (
    ANALYSIS_KIWOOM_PROMPT_V1,
    ANALYSIS_UPBIT_PROMPT_V1,
    prompt_versions_for,
    schema_for,
)
from stock_platform.operation.kiwoom_dual_llm.clean_research import (
    classify_kiwoom_research_row,
)
from stock_platform.operation.kiwoom_dual_llm.outcome import (
    label_from_returns,
    mark_truncated_by_market_close,
    try_enrich_outcome_from_minute_bars,
)
from stock_platform.operation.upbit_market_context.rag_retrieval import (
    retrieve_similar_cases,
)


def test_market_isolation_helpers() -> None:
    assert same_market("UPBIT", "CRYPTO")
    assert same_market("KIWOOM", "KRX")
    assert not same_market("UPBIT", "KIWOOM")
    assert prompt_versions_for(MARKET_UPBIT)["analysis"] == ANALYSIS_UPBIT_PROMPT_V1
    assert prompt_versions_for(MARKET_KIWOOM)["analysis"] == ANALYSIS_KIWOOM_PROMPT_V1
    assert schema_for(MARKET_KIWOOM).startswith("kiwoom_")


def test_upbit_rag_blocks_kiwoom_market(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    out = retrieve_similar_cases(
        session,
        detected_at=datetime.now(timezone.utc),
        technical={"rsi14": 50},
        candidate={"score": 70},
        market=MARKET_KIWOOM,
    )
    assert out["examples"] == []
    assert out["cross_market_rag_count"] == 0
    assert out["excluded"]["cross_market_blocked"] == 1


def test_kiwoom_clean_excludes_imported_and_forced() -> None:
    bad = classify_kiwoom_research_row(
        input_json={
            "market": "KIWOOM",
            "reference_price": "1000",
            "provenance": {
                "imported_position": True,
                "source": "MA_ENTRY_EVALUATION",
                "signal_id": "x",
                "fingerprint": "y",
            },
        },
        output_json={"market": "KIWOOM"},
    )
    assert bad["clean"] is False
    assert "IMPORTED_POSITION" in bad["exclusions"]

    forced = classify_kiwoom_research_row(
        input_json={
            "market": "KIWOOM",
            "reference_price": "1000",
            "provenance": {
                "forced": True,
                "source": "MA_ENTRY_EVALUATION",
                "signal_id": "x",
                "fingerprint": "y",
            },
        },
        output_json={"market": "KIWOOM"},
    )
    assert forced["clean"] is False

    ok = classify_kiwoom_research_row(
        input_json={
            "market": "KIWOOM",
            "reference_price": "1000",
            "provenance": {
                "source": "MA_ENTRY_EVALUATION",
                "signal_id": "sig",
                "fingerprint": "fp",
                "forced": False,
                "imported_position": False,
            },
        },
        output_json={"market": "KIWOOM", "outcome_status": "PENDING"},
    )
    assert ok["clean"] is True


def test_kiwoom_truncated_outcome_no_invented_price() -> None:
    det = datetime(2026, 8, 25, 6, 0, tzinfo=timezone.utc)
    pending = try_enrich_outcome_from_minute_bars(
        MagicMock(),
        symbol="005930",
        entry_price=70000.0,
        evaluated_at=det,
        bars=None,
    )
    assert pending["status"] == "PENDING"
    assert pending["return_5m"] is None
    trunc = mark_truncated_by_market_close(pending)
    assert trunc["status"] == "TRUNCATED_BY_MARKET_CLOSE"
    assert trunc["truncated"] is True
    assert label_from_returns(
        return_5m=-0.8, mfe=0.1, early_dump=True, truncated=False
    ) == "EARLY_DUMP"


def test_kiwoom_trading_shadow_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_platform.operation.kiwoom_dual_llm import trading_shadow as ts

    monkeypatch.setattr(ts, "dual_llm_enabled", lambda: True)
    monkeypatch.setattr(ts, "trading_shadow_enabled", lambda: True)

    def _ok(**_k):
        return {
            "ok": True,
            "timeout": False,
            "latency_ms": 5,
            "model": "qwen3.5:2b",
            "parsed": {
                "recommendation": "HOLD",
                "entry_quality_score": 40,
                "early_dump_risk": "HIGH",
                "fee_churn_risk": "LOW",
                "event_risk": "MEDIUM",
                "confidence": 0.6,
                "risk_flags": ["DISCLOSURE"],
                "reason_codes": ["EVENT"],
                "reason_ko": "공시 리스크",
            },
        }

    monkeypatch.setattr(ts, "chat_json_sync", _ok)
    out = ts.run_kiwoom_trading_llm_shadow(
        {"candidate": {"symbol": "005930"}, "technical": {"rsi14": 55}},
        analysis_summary={"risk_level": "HIGH", "disclosure_state": "NEGATIVE"},
        rag_examples=[
            {
                "case_id": "kiwoom_analysis:1",
                "market": "UPBIT",  # must be filtered out
                "similarity_score": 0.9,
            },
            {
                "case_id": "kiwoom_analysis:2",
                "market": "KIWOOM",
                "similarity_score": 0.8,
                "actual_label": "EARLY_DUMP",
            },
        ],
    )
    assert out["ok"] is True
    assert out["market"] == MARKET_KIWOOM
    assert out["event_risk"] == "MEDIUM"
    assert out["affects_real"] is False
    assert out["affects_ma_evaluator"] is False
    assert out["rag_example_count"] == 1  # UPBIT example filtered


def test_schedule_hook_does_not_raise() -> None:
    from stock_platform.operation.kiwoom_dual_llm.entry_shadow import (
        schedule_kiwoom_entry_shadow,
    )
    from stock_platform.realtime.strategy_signal import StrategySignal
    from decimal import Decimal

    sig = StrategySignal(
        signal_id="sig_test",
        fingerprint="fp_test",
        scope_key="uba:1",
        user_id=1,
        account_kind="USER_BROKER",
        account_id=1381,
        strategy_id=17579,
        strategy_version="1",
        broker_code="KIWOOM",
        market_type="STOCK",
        symbol="005930",
        signal_type="BUY",
        generated_at=datetime.now(timezone.utc),
        event_time=datetime.now(timezone.utc),
        reference_price=Decimal("70000"),
        reason_code="MA_GOLDEN_CROSS",
        metadata={},
    )
    # enabled path schedules thread — should not raise
    schedule_kiwoom_entry_shadow(sig)


def test_kiwoom_api_status(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from stock_platform.api.deps_admin import require_admin
    from stock_platform.api.v1.admin_kiwoom_dual_llm import router as kw_router
    from stock_platform.database.session import get_db_session

    app = FastAPI()
    app.include_router(kw_router)

    async def _admin():
        return {"role": "ADMIN"}

    session = MagicMock()
    session.scalars.return_value = iter([])
    app.dependency_overrides[require_admin] = _admin
    app.dependency_overrides[get_db_session] = lambda: session

    client = TestClient(app)
    r = client.get("/api/v1/admin/kiwoom/dual-llm/status")
    assert r.status_code == 200
    body = r.json()
    assert body["market"] == "KIWOOM"
    assert body["TRADING_LLM_MODE"] == "SHADOW"
    assert body["MA_EVALUATOR_LLM_DEPENDENCY"] is False
    assert body["LORA_TRAINING_STARTED"] is False
    assert body["KIWOOM_TRADING_MUTATION"] == 0
