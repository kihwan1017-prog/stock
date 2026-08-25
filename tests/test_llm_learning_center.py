"""LLM Learning Center — unit tests (READ ONLY, no REAL mutate)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.llm_learning_center.assistant import (
    classify_intent,
    redact_secrets,
)
from stock_platform.operation.llm_learning_center.entities import VALID_FEEDBACK_LABELS
from stock_platform.operation.llm_learning_center.service import (
    MARKET_ALL,
    MARKET_KIWOOM,
    MARKET_UPBIT,
    build_learning_stages,
    build_summary,
)


def test_classify_intent_learning_status() -> None:
    assert classify_intent("현재 학습 상태 알려줘") == "learning_status"
    assert classify_intent("MA Confirm2 결과는?") == "forward_shadow"
    assert classify_intent("Teacher가 발견한 문제는?") == "teacher_findings"
    assert classify_intent("LoRA는 언제 가능한가?") == "lora_readiness"


def test_classify_intent_mutation_refusal() -> None:
    assert classify_intent("지금 매수해") == "mutation_refusal"
    assert classify_intent("전략 바꿔줘") == "mutation_refusal"


def test_redact_secrets() -> None:
    raw = "api_key=supersecret123 Bearer abc.def.ghi"
    out = redact_secrets(raw)
    assert "supersecret123" not in out
    assert "[REDACTED]" in out


def test_feedback_labels_complete() -> None:
    assert "EXCLUDE_FROM_TRAINING" in VALID_FEEDBACK_LABELS
    assert "GOOD_DECISION" in VALID_FEEDBACK_LABELS


def test_build_summary_empty_session() -> None:
    session = MagicMock()
    session.scalars.return_value = iter([])
    with patch(
        "stock_platform.operation.llm_learning_center.service._upbit_clean_count",
        return_value=0,
    ):
        with patch(
            "stock_platform.operation.llm_learning_center.service.summarize_forward_shadow",
            return_value={"baseline": {"sample_count": 0}},
        ):
            out = build_summary(session, market=MARKET_UPBIT)
    assert out["schema"] == "llm_learning_summary_v1"
    assert out["market"] == MARKET_UPBIT
    assert out["CROSS_MARKET_RAG"] == 0
    assert out["safety"]["REAL_ORDER_MUTATION"] == 0
    assert out["safety"]["LORA_TRAINING_STARTED"] is False
    assert out["trading"]["mode"] == "SHADOW"


def test_build_learning_stages_market_isolation() -> None:
    session = MagicMock()
    session.scalars.return_value = iter([])
    with patch(
        "stock_platform.operation.llm_learning_center.service._upbit_clean_count",
        return_value=0,
    ):
        with patch(
            "stock_platform.operation.llm_learning_center.service.summarize_forward_shadow",
            return_value={"baseline": {"sample_count": 0}},
        ):
            kiwoom = build_learning_stages(session, market=MARKET_KIWOOM)
    forward = next(s for s in kiwoom["stages"] if s["id"] == "FORWARD_SHADOW")
    assert forward["status_ko"] == "해당 없음"


def test_ask_assistant_read_only_no_mutation() -> None:
    from stock_platform.operation.llm_learning_center.assistant import ask_assistant

    session = MagicMock()
    session.scalars.return_value = iter([])
    with patch(
        "stock_platform.operation.llm_learning_center.service._upbit_clean_count",
        return_value=0,
    ):
        with patch(
            "stock_platform.operation.llm_learning_center.service.summarize_forward_shadow",
            return_value={"baseline": {"sample_count": 0}},
        ):
            out = ask_assistant(session, question="지금 매도해", market=MARKET_ALL, use_llm=False)
    assert out["read_only"] is True
    assert out["REAL_ORDER_MUTATION"] == 0
    assert out["intent"] == "mutation_refusal"
    assert out["answer"].get("read_only_refusal") is True


def test_api_router_prefix() -> None:
    from stock_platform.api.v1.admin_llm_learning import router

    assert router.prefix == "/api/v1/admin/llm-learning"
