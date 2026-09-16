"""CLEAN RAG + Feedback learning pipeline — unit tests (no REAL mutate)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_market_context.feedback_scoring import (
    classify_prediction_correctness,
)
from stock_platform.operation.upbit_market_context.learning_dataset import (
    assign_dataset_tier,
    export_jsonl_rows,
    sample_stage,
)
from stock_platform.operation.upbit_market_context.prompt_versions import (
    ANALYSIS_PROMPT_VERSION,
    TRADING_PROMPT_VERSION,
    is_dual_llm_schema,
)
from stock_platform.operation.upbit_market_context.rag_retrieval import (
    assert_no_lookahead,
    candidate_feature_vector,
    rag_cache,
    similarity_score,
)
from stock_platform.operation.upbit_market_context.teacher_llm import (
    should_call_teacher,
)


def test_prompt_and_schema_versions() -> None:
    assert ANALYSIS_PROMPT_VERSION.startswith("analysis_")
    assert TRADING_PROMPT_VERSION.startswith("trading_")
    assert is_dual_llm_schema("upbit_dual_llm_rag_v1")
    assert is_dual_llm_schema("upbit_dual_llm_shadow_v1")
    assert is_dual_llm_schema("kiwoom_dual_llm_rag_v1")
    assert not is_dual_llm_schema("legacy")


def test_similarity_stable() -> None:
    q = candidate_feature_vector(
        technical={"rsi14": 60.0, "ma_separation_pct": 0.2, "volume_surge": 2.0},
        candidate={"score": 80.0},
        analysis={"risk_factors": ["MARKET_WEAK"]},
    )
    case = {
        "entry_context": {
            "rsi": 61.0,
            "ma_separation_pct": 0.21,
            "volume_ratio": 2.1,
            "scanner_score": 81.0,
            "analysis_risk_flags": ["MARKET_WEAK"],
        }
    }
    a = similarity_score(q, case)
    b = similarity_score(q, case)
    assert a == b
    assert 0.0 <= a <= 1.0


def test_rag_no_lookahead_assert() -> None:
    det = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    ok = [
        {
            "outcome_completed_at": (det - timedelta(hours=1)).isoformat(),
        }
    ]
    bad = [
        {
            "outcome_completed_at": (det + timedelta(minutes=1)).isoformat(),
        }
    ]
    assert assert_no_lookahead(ok, detected_at=det) is True
    assert assert_no_lookahead(bad, detected_at=det) is False


def test_rag_cache_ttl() -> None:
    rag_cache._data.clear()
    rag_cache.hits = 0
    rag_cache.misses = 0
    rag_cache.put("k1", {"examples": []}, ttl_seconds=60)
    assert rag_cache.get("k1") is not None
    assert rag_cache.hits == 1
    # expire manually
    key = next(iter(rag_cache._data.keys()))
    expires, payload = rag_cache._data[key]
    rag_cache._data[key] = (expires - 10_000, payload)
    assert rag_cache.get("k1") is None
    assert rag_cache.misses >= 1


def test_feedback_classifications() -> None:
    assert (
        classify_prediction_correctness(
            recommendation="ALLOW",
            label="GOOD_FOLLOW_THROUGH",
            early_dump=False,
            return_5m=0.3,
            return_60m=0.8,
            mfe=1.2,
            mae=-0.1,
        )
        == "ALLOW_SUCCESS"
    )
    assert (
        classify_prediction_correctness(
            recommendation="ALLOW",
            label="EARLY_DUMP_5M",
            early_dump=True,
            return_5m=-0.8,
            return_60m=-1.0,
            mfe=0.1,
            mae=-1.0,
        )
        == "ALLOW_EARLY_DUMP"
    )
    assert (
        classify_prediction_correctness(
            recommendation="HOLD",
            label="EARLY_DUMP_5M",
            early_dump=True,
            return_5m=-0.8,
            return_60m=-1.0,
            mfe=0.0,
            mae=-1.0,
        )
        == "HOLD_AVOIDED_LOSS"
    )
    assert (
        classify_prediction_correctness(
            recommendation="HOLD",
            label="GOOD_FOLLOW_THROUGH",
            early_dump=False,
            return_5m=0.5,
            return_60m=2.0,
            mfe=2.5,
            mae=-0.1,
        )
        == "HOLD_MISSED_WINNER"
    )
    assert (
        classify_prediction_correctness(
            recommendation="REDUCE",
            label="EARLY_DUMP_5M",
            early_dump=True,
            return_5m=-1.0,
            return_60m=-1.2,
            mfe=0.0,
            mae=-1.2,
        )
        == "REDUCE_AVOIDED_LOSS"
    )


def test_dataset_tiers_and_stage() -> None:
    assert (
        assign_dataset_tier(
            clean=True,
            no_lookahead=True,
            canonical_price=True,
            outcome_complete=True,
            prediction_parse_valid=True,
            context_full=True,
        )
        == "GOLD"
    )
    assert (
        assign_dataset_tier(
            clean=True,
            no_lookahead=True,
            canonical_price=True,
            outcome_complete=True,
            prediction_parse_valid=False,
            context_full=False,
        )
        == "SILVER"
    )
    assert (
        assign_dataset_tier(
            clean=False,
            no_lookahead=True,
            canonical_price=True,
            outcome_complete=True,
            prediction_parse_valid=True,
            context_full=True,
            legacy=True,
        )
        == "EXCLUDED"
    )
    assert sample_stage(37)["SAMPLE_STAGE"] == "COLLECTION_ONLY"
    assert sample_stage(100)["SAMPLE_STAGE"] == "DIAGNOSTIC"
    assert sample_stage(500)["SAMPLE_STAGE"] == "PRIMARY_REVIEW"
    assert sample_stage(1000)["SAMPLE_STAGE"] == "LORA_DATASET_REVIEW_READY"
    assert sample_stage(1000)["LORA_TRAINING_STARTED"] is False


def test_export_no_leakage_and_research_mode() -> None:
    examples = [
        {
            "dataset_tier": "GOLD",
            "input_snapshot": {
                "detected_at": "2026-08-20T00:00:00+00:00",
                "technical": {"rsi14": 50},
            },
            "analysis_prediction": {
                "market_summary": "m",
                "asset_summary": "a",
                "news_summary": "n",
                "risk_factors": [],
                "tone": "NEUTRAL",
            },
            "trading_prediction": {
                "recommendation": "HOLD",
                "entry_quality_score": 40,
                "early_dump_risk": "HIGH",
                "fee_churn_risk": "LOW",
                "reason_codes": ["R1"],
            },
            "rag_context": {"examples": [{"case_id": "shadow:1"}]},
            "split": {"suggested": "TRAIN"},
            # 현재 후보 미래 outcome은 trading export에 넣지 않음
            "actual_outcome": {"return_60m": 9.9},
        }
    ]
    out = export_jsonl_rows(examples, kind="trading", clean_n=37)
    assert out["export_mode"] == "RESEARCH_EXPORT_ONLY"
    assert out["LORA_TRAINING_STARTED"] is False
    assert out["line_count"] == 1
    line = out["lines"][0]
    assert "return_60m" not in line or '"no_current_future_outcome": true' in line
    assert "9.9" not in line


def test_teacher_selective_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_platform.operation.upbit_market_context import teacher_llm as tl

    monkeypatch.setattr(
        tl,
        "get_settings",
        lambda: SimpleNamespace(
            teacher_llm_max_rate=0.99,
            teacher_llm_confidence_threshold=0.65,
            teacher_llm_sample_rate=0.0,
        ),
    )
    # conflict: risk high + ALLOW high conf
    d = should_call_teacher(
        analysis={"tone": "CAUTION", "risk_factors": ["MARKET_WEAK"]},
        trading={"ok": True, "recommendation": "ALLOW", "confidence": 0.9},
    )
    assert d["trigger"] is True
    assert "ANALYSIS_TRADING_CONFLICT" in d["reasons"]

    d2 = should_call_teacher(
        analysis={"tone": "NEUTRAL", "risk_factors": []},
        trading={"ok": True, "recommendation": "ALLOW", "confidence": 0.9},
        feedback={},
    )
    assert d2["trigger"] is False


def test_trading_schema_includes_fee_churn(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_platform.operation.upbit_market_context import trading_llm_shadow as tls
    from stock_platform.operation.upbit_market_context.schemas import LlmContextInput

    monkeypatch.setattr(tls, "dual_llm_enabled", lambda: True)
    monkeypatch.setattr(tls, "trading_shadow_enabled", lambda: True)

    def _ok(**_k):
        return {
            "ok": True,
            "timeout": False,
            "error": None,
            "latency_ms": 12,
            "model": "qwen3.5:2b",
            "model_role": "TRADING",
            "parsed": {
                "recommendation": "HOLD",
                "entry_quality_score": 42,
                "early_dump_risk": "HIGH",
                "fee_churn_risk": "MEDIUM",
                "confidence": 0.7,
                "risk_flags": ["EARLY_DUMP"],
                "reason_codes": ["RAG_SIMILAR_DUMP"],
                "reason_ko": "유사 사례 early dump",
            },
        }

    monkeypatch.setattr(tls, "chat_json_sync", _ok)
    inp = LlmContextInput(
        context_as_of="2026-08-25T00:00:00+00:00",
        candidate={"symbol": "KRW-BTC"},
        technical={"rsi14": 70},
    )
    out = tls.run_trading_llm_shadow(
        inp,
        analysis_summary={"tone": "CAUTION", "risk_factors": ["X"]},
        rag_examples=[
            {
                "case_id": "shadow:9",
                "similarity_score": 0.9,
                "actual_label": "EARLY_DUMP_5M",
                "mfe": 0.1,
                "mae": -1.0,
                "entry_summary": {"rsi": 68},
            }
        ],
    )
    assert out["ok"] is True
    assert out["fee_churn_risk"] == "MEDIUM"
    assert out["prompt_version"] == TRADING_PROMPT_VERSION
    assert out["affects_real"] is False
    assert out["mode"] == "SHADOW"
    assert out["rag_example_count"] == 1


def test_api_rag_feedback_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from stock_platform.api.deps_admin import require_admin
    from stock_platform.api.v1.admin_upbit_dual_llm import router as dual_router
    from stock_platform.database.session import get_db_session

    app = FastAPI()
    app.include_router(dual_router)

    async def _admin():
        return {"role": "ADMIN"}

    session = MagicMock()
    session.scalars.return_value = iter([])

    app.dependency_overrides[require_admin] = _admin
    app.dependency_overrides[get_db_session] = lambda: session

    monkeypatch.setattr(
        "stock_platform.api.v1.admin_upbit_dual_llm.assign_clean_forward_obs",
        lambda _rows: [],
    )

    client = TestClient(app)
    r = client.get("/api/v1/admin/upbit/dual-llm/rag-feedback")
    assert r.status_code == 200
    body = r.json()
    assert body["schema"] == "upbit_dual_llm_rag_feedback_v1"
    assert body["research_only"] is True

    st = client.get("/api/v1/admin/upbit/dual-llm/status")
    assert st.status_code == 200
    sb = st.json()
    assert sb["RAG_IMPLEMENTED"] is True
    assert sb["TRADING_LLM_MODE"] == "SHADOW"
    assert sb["LORA_TRAINING_STARTED"] is False
    assert sb["TRADING_LLM_REAL_GATE_MUTATION"] == 0
    assert sb["TEACHER_LLM_MODEL"]
    assert sb["SAMPLE_STAGE"] == "COLLECTION_ONLY"
