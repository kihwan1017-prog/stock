"""Trading Decision contract — HOLD-collapse 수정 회귀. PROD DB 없음."""

from __future__ import annotations

from stock_platform.operation.dual_llm.prompt_versions import (
    TRADING_PROMPT_VERSION,
    TRADING_UPBIT_PROMPT_V1,
    TRADING_UPBIT_PROMPT_V2,
    prompt_versions_for,
)
from stock_platform.operation.upbit_market_context.schemas import LlmContextInput
from stock_platform.operation.upbit_market_context.trading_decision_contract import (
    FORBIDDEN_PROMPT_PHRASES,
    TRADING_SYSTEM_PROMPT_V2,
    TRADING_USER_INSTRUCTION_V2,
    build_trading_decision_payload,
    extract_safety_flags,
    prompt_forbids_aggressive_allow,
)
from stock_platform.operation.upbit_market_context.trading_llm_shadow import (
    SYSTEM_PROMPT,
    VALID_REC,
)


def test_prompt_version_is_v2_not_overwrite_v1() -> None:
    assert TRADING_UPBIT_PROMPT_V1 == "trading_upbit_prompt_v1"
    assert TRADING_PROMPT_VERSION == TRADING_UPBIT_PROMPT_V2
    assert prompt_versions_for("UPBIT")["trading"] == TRADING_UPBIT_PROMPT_V2


def test_prompt_semantics_shadow_is_not_always_hold() -> None:
    text = SYSTEM_PROMPT + TRADING_USER_INSTRUCTION_V2
    assert SYSTEM_PROMPT == TRADING_SYSTEM_PROMPT_V2
    assert "항상 HOLD" in SYSTEM_PROMPT
    assert "주문 실행 명령이 아닙니다" in SYSTEM_PROMPT
    assert "CANDIDATE_FOR_DOWNSTREAM_RISK_EVALUATION" not in FORBIDDEN_PROMPT_PHRASES
    assert "Risk Engine" in SYSTEM_PROMPT
    assert "optional" in SYSTEM_PROMPT
    assert prompt_forbids_aggressive_allow(text)
    for phrase in FORBIDDEN_PROMPT_PHRASES:
        assert phrase not in text
    # 구 문장은 ALLOW를 주문으로 오해시킬 수 있음
    assert "REAL 주문을 만들지 마세요" not in SYSTEM_PROMPT


def test_payload_marks_optional_news_rag_absent() -> None:
    inp = LlmContextInput(
        context_as_of="2026-09-16T00:00:00+00:00",
        candidate={
            "symbol": "KRW-BTC",
            "rank": 1,
            "score": 0.8,
            "recommendation": "HOLD",
            "last_price": 1000,
        },
        technical={"rsi14": 58.0, "signed_change_rate": 0.045, "trade_price": 1000},
        market_context={"fresh": True, "kill_switch": False},
        news=[],
    )
    payload = build_trading_decision_payload(
        inp,
        analysis_summary={
            "ok": True,
            "tone": "BULLISH",
            "market_summary": "상승",
            "confidence": 0.7,
        },
        rag_examples=[],
    )
    assert payload["optional_context"]["news"]["available"] is False
    assert payload["optional_context"]["rag"]["available"] is False
    assert payload["optional_context"]["news"]["absence_is_not_automatic_hold"] is True
    assert payload["decision_contract"]["shadow_means_always_hold"] is False
    assert payload["decision_contract"]["recommendation_is_order"] is False
    # 출력 enum과 이름이 같은 recommendation 키를 candidate에 남기지 않음
    assert "recommendation" not in payload["candidate"]
    assert payload["candidate"]["scanner_recommendation"] == "HOLD"
    assert payload["candidate"]["scanner_recommendation_non_binding"] is True
    assert payload["safety"]["hard_safety_violation"] is False


def test_hard_safety_flags_from_market_context() -> None:
    flags = extract_safety_flags(
        {
            "kill_switch": True,
            "stale": True,
            "risk_exceeded": True,
            "authorization_valid": False,
        },
        price_valid=False,
    )
    assert flags["hard_safety_violation"] is True
    assert flags["kill_switch"] is True
    assert flags["stale"] is True
    assert flags["risk_exceeded"] is True
    assert flags["authorization_expired"] is True
    assert flags["invalid_price"] is True


def test_parser_keeps_allow_and_rejects_unknown(monkeypatch) -> None:
    from types import SimpleNamespace

    from stock_platform.operation.upbit_market_context import trading_llm_shadow as tls

    rec = "ALLOW"
    assert rec in VALID_REC
    assert "UNKNOWN" not in VALID_REC

    captured: dict[str, object] = {}

    def _ok(**kwargs):
        captured["system"] = kwargs["system_prompt"]
        captured["user"] = kwargs["user_prompt"]
        return {
            "ok": True,
            "timeout": False,
            "error": None,
            "latency_ms": 1,
            "model": "qwen3.5:4b",
            "model_role": "TRADING",
            "parsed": {
                "recommendation": "ALLOW",
                "entry_quality_score": 80,
                "early_dump_risk": "LOW",
                "fee_churn_risk": "LOW",
                "confidence": 0.8,
                "risk_flags": [],
                "reason_codes": ["STRONG_TREND"],
                "reason_ko": "근거 충분",
            },
        }

    monkeypatch.setattr(tls, "dual_llm_enabled", lambda: True)
    monkeypatch.setattr(tls, "trading_shadow_enabled", lambda: True)
    monkeypatch.setattr(
        tls,
        "trading_config",
        lambda: SimpleNamespace(
            model="qwen3.5:4b",
            temperature=0.1,
            max_tokens=256,
        ),
    )
    monkeypatch.setattr(tls, "chat_json_sync", _ok)
    inp = LlmContextInput(
        context_as_of="2026-09-16T00:00:00+00:00",
        candidate={"symbol": "KRW-ETH", "last_price": 2000},
        technical={"trade_price": 2000, "signed_change_rate": 0.05},
        market_context={"fresh": True},
    )
    out = tls.run_trading_llm_shadow(
        inp,
        analysis_summary={"tone": "BULLISH", "ok": True, "confidence": 0.7},
    )
    assert out["ok"] is True
    assert out["recommendation"] == "ALLOW"
    assert out["affects_real"] is False
    assert out["mode"] == "SHADOW"
    assert "항상 HOLD" in str(captured["system"])
    assert "scanner_recommendation" in str(captured["user"])


def test_invalid_recommendation_fail_closed_not_allow(monkeypatch) -> None:
    from types import SimpleNamespace

    from stock_platform.operation.upbit_market_context import trading_llm_shadow as tls

    def _bad(**_k):
        return {
            "ok": True,
            "timeout": False,
            "error": None,
            "latency_ms": 1,
            "model": "qwen3.5:4b",
            "model_role": "TRADING",
            "parsed": {
                "recommendation": "BUY",
                "entry_quality_score": 90,
                "early_dump_risk": "LOW",
                "fee_churn_risk": "LOW",
                "confidence": 0.9,
                "risk_flags": [],
                "reason_codes": ["X"],
            },
        }

    monkeypatch.setattr(tls, "dual_llm_enabled", lambda: True)
    monkeypatch.setattr(tls, "trading_shadow_enabled", lambda: True)
    monkeypatch.setattr(
        tls,
        "trading_config",
        lambda: SimpleNamespace(
            model="qwen3.5:4b",
            temperature=0.1,
            max_tokens=256,
        ),
    )
    monkeypatch.setattr(tls, "chat_json_sync", _bad)
    inp = LlmContextInput(
        context_as_of="2026-09-16T00:00:00+00:00",
        candidate={"symbol": "KRW-X"},
    )
    out = tls.run_trading_llm_shadow(inp, analysis_summary={"ok": True})
    assert out["ok"] is False
    assert out.get("recommendation") != "ALLOW"
    assert out["fallback_to_heuristic"] is True
    assert "INVALID_RECOMMENDATION" in str(out.get("error"))
