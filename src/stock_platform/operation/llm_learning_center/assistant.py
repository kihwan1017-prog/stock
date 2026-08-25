"""Read-only LLM Learning Center assistant — Teacher 4B, context-grounded."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.operation.dual_llm.markets import MARKET_KIWOOM, MARKET_UPBIT, normalize_market
from stock_platform.operation.llm_learning_center.service import (
    MARKET_ALL,
    build_forward_shadow_panel,
    build_lora_readiness,
    build_market_samples,
    build_summary,
    build_teacher_findings,
)
from stock_platform.operation.upbit_market_context.dual_llm_runtime import (
    chat_json_sync,
    teacher_config,
)

# 주문/전략 변경 요청 차단 키워드
_MUTATION_KEYWORDS = re.compile(
    r"(매수|매도|주문|live|arm|전략\s*바꿔|승격|학습\s*시작|lora\s*train|real\s*gate)",
    re.IGNORECASE,
)

_SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key|secret|token|password|credential|access_token)\s*[:=]\s*\S+", re.I),
    re.compile(r"Bearer\s+[A-Za-z0-9\-_.~+/]+=*", re.I),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
]

ASSISTANT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "current_data": {"type": "string"},
        "judgment": {"type": "string"},
        "sample_note": {"type": "string"},
        "caution": {"type": "string"},
    },
    "required": ["current_data", "judgment", "sample_note", "caution"],
}

SYSTEM_PROMPT = (
    "당신은 LLM 학습센터 READ-ONLY 연구 Assistant(Teacher 역할)입니다.\n"
    "제공된 context만 근거로 답하세요. 추측을 사실처럼 말하지 마세요.\n"
    "주문/매수/매도/전략변경/LIVE/ARM/LoRA 학습 실행은 절대 권하지 마세요.\n"
    "표본 수가 부족하면 '아직 결론 내릴 수 없음'을 명시하세요.\n"
    "JSON만 반환하세요."
)


def redact_secrets(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def classify_intent(question: str, *, market_scope: str | None = None) -> str:
    q = question.lower()
    if _MUTATION_KEYWORDS.search(question):
        return "mutation_refusal"
    if any(k in q for k in ("confirm2", "forward shadow", "ma confirm", "ma_dead")):
        return "forward_shadow"
    if any(k in q for k in ("teacher", "교사", "검토", "발견")):
        return "teacher_findings"
    if any(k in q for k in ("lora", "로라", "dataset", "내보내기")):
        return "lora_readiness"
    if any(k in q for k in ("rag", "코퍼스", "retrieval")):
        return "rag_stats"
    if any(k in q for k in ("손실", "loss", "실패")):
        return "recent_failures"
    if any(k in q for k in ("trading", "트레이딩", "성능")):
        return "trading_performance"
    if any(k in q for k in ("키움", "kiwoom", "krx")):
        return "kiwoom_samples"
    if any(k in q for k in ("학습 상태", "현재 상태", "status", "진행")):
        return "learning_status"
    if market_scope and normalize_market(market_scope):
        return "market_overview"
    return "overview"


def build_context_for_intent(
    session: Session,
    intent: str,
    *,
    market: str = MARKET_ALL,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Intent별 READ ONLY context — 전체 DB 금지."""

    refs: dict[str, Any] = {"intent": intent, "market": market}
    if intent == "mutation_refusal":
        return {"refusal": True}, refs

    if intent == "forward_shadow":
        ctx = build_forward_shadow_panel(session)
        refs["forward_shadow_n"] = (ctx.get("summary") or {}).get("baseline", {}).get(
            "sample_count", 0
        )
        return ctx, refs

    if intent == "teacher_findings":
        ctx = build_teacher_findings(session, market=market, limit=10)
        refs["teacher_reviews"] = ctx.get("total", 0)
        return ctx, refs

    if intent == "lora_readiness":
        ctx = build_lora_readiness(session, market=market)
        refs["LORA_TRAINING_STARTED"] = False
        return ctx, refs

    if intent == "rag_stats":
        summary = build_summary(session, market=market)
        ctx = {"rag": summary.get("rag"), "samples": summary.get("samples")}
        refs.update(
            {
                "corpus_size": summary.get("rag", {}).get("corpus_size"),
                "gold": summary.get("rag", {}).get("gold"),
            }
        )
        return ctx, refs

    if intent in {"recent_failures", "trading_performance"}:
        findings = build_teacher_findings(session, market=market, limit=5)
        summary = build_summary(session, market=market)
        ctx = {
            "trading": summary.get("trading"),
            "teacher_samples": findings.get("items"),
        }
        refs["predictions"] = summary.get("trading", {}).get("predictions")
        refs["outcomes"] = summary.get("trading", {}).get("outcomes")
        return ctx, refs

    if intent == "kiwoom_samples":
        ctx = build_market_samples(session, market=MARKET_KIWOOM)
        refs["KIWOOM_CLEAN"] = ctx.get("CLEAN")
        return ctx, refs

    # learning_status / overview / market_overview
    summary = build_summary(session, market=market)
    refs.update(
        {
            "UPBIT_CLEAN": (
                summary.get("markets", {}).get(MARKET_UPBIT, {}).get("CLEAN")
                if market == MARKET_ALL
                else summary.get("samples", {}).get("CLEAN")
            ),
            "predictions": summary.get("trading", {}).get("predictions"),
            "teacher_reviews": summary.get("teacher", {}).get("reviews"),
        }
    )
    if market == MARKET_ALL:
        refs["KIWOOM_CLEAN"] = summary.get("markets", {}).get(MARKET_KIWOOM, {}).get("CLEAN")
    return summary, refs


def _fallback_answer(context: dict[str, Any], intent: str) -> dict[str, Any]:
    """Ollama 불가 시 rule-based grounded answer."""

    if intent == "mutation_refusal":
        return {
            "current_data": "이 화면은 조회/연구 전용입니다.",
            "judgment": "주문·전략·LIVE·LoRA 학습 실행 요청은 처리하지 않습니다.",
            "sample_note": "—",
            "caution": "TRADING 2B 판단을 변경하지 않습니다.",
            "read_only_refusal": True,
        }

    samples = context.get("samples") or context
    clean = samples.get("CLEAN") or samples.get("clean") or 0
    return {
        "current_data": f"집계 context intent={intent} · CLEAN≈{clean}",
        "judgment": "Teacher LLM 응답 unavailable — 서버 context만 표시합니다.",
        "sample_note": f"표본 {clean} — 100 미만이면 본 평가 전입니다.",
        "caution": "추정 정확도/승격 결론을 내리지 마세요.",
        "llm_unavailable": True,
    }


def ask_assistant(
    session: Session,
    *,
    question: str,
    market: str = MARKET_ALL,
    use_llm: bool = True,
) -> dict[str, Any]:
    """POST /ask handler core — READ ONLY."""

    q_clean = redact_secrets(question.strip())
    intent = classify_intent(q_clean, market_scope=market)
    context, refs = build_context_for_intent(session, intent, market=market)

    if intent == "mutation_refusal":
        parsed = _fallback_answer(context, intent)
        return {
            "schema": "llm_learning_assistant_answer_v1",
            "intent": intent,
            "question": q_clean,
            "answer": parsed,
            "context_refs": refs,
            "model": None,
            "read_only": True,
            "REAL_ORDER_MUTATION": 0,
        }

    cfg = teacher_config()
    user_prompt = (
        f"질문: {q_clean}\n\n"
        f"READ ONLY context (JSON):\n{context}\n\n"
        "섹션: [현재 데이터][판단][표본 수][주의사항] 형식으로 JSON 필드에 담으세요."
    )

    llm_result: dict[str, Any] | None = None
    if use_llm:
        llm_result = chat_json_sync(
            config=cfg,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_schema=ASSISTANT_SCHEMA,
        )

    if llm_result and llm_result.get("ok") and isinstance(llm_result.get("parsed"), dict):
        parsed = llm_result["parsed"]
        for k in ("current_data", "judgment", "sample_note", "caution"):
            if k in parsed and isinstance(parsed[k], str):
                parsed[k] = redact_secrets(parsed[k])
    else:
        parsed = _fallback_answer(context, intent)
        if llm_result:
            parsed["llm_error"] = str(llm_result.get("error") or "LLM_ERROR")[:120]

    return {
        "schema": "llm_learning_assistant_answer_v1",
        "intent": intent,
        "question": q_clean,
        "answer": parsed,
        "context_refs": refs,
        "model": cfg.model,
        "read_only": True,
        "REAL_ORDER_MUTATION": 0,
        "latency_ms": (llm_result or {}).get("latency_ms"),
    }


__all__ = [
    "ask_assistant",
    "build_context_for_intent",
    "classify_intent",
    "redact_secrets",
    "ASSISTANT_SCHEMA",
    "SYSTEM_PROMPT",
]
